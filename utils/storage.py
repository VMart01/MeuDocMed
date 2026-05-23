"""
utils/storage.py — Abstração de armazenamento de arquivos.

Em desenvolvimento (sem CLOUDINARY_CLOUD_NAME): salva/lê do disco local.
Em produção (com CLOUDINARY_CLOUD_NAME):        usa Cloudinary (resource_type=raw).

Estratégia de stored_id:
  - Cloudinary: guarda o secure_url completo (ex: https://res.cloudinary.com/…)
                Isso elimina qualquer ambiguidade de reconstrução de URL.
  - Local:      guarda só o nome do arquivo (ex: 'abc123def.pdf')

A interface pública é:
  upload_file(file_bytes, original_filename)  -> stored_id (str)
  get_file_bytes(stored_id, upload_folder)    -> bytes | None
  delete_stored_file(stored_id, upload_folder)-> bool
"""
import logging
import os
import re
import uuid
import tempfile

from utils.file_utils import get_extension

logger = logging.getLogger(__name__)


# ── detecção de backend ───────────────────────────────────────────────────────

def _cloudinary_configured() -> bool:
    return bool(os.environ.get('CLOUDINARY_CLOUD_NAME'))


def _init_cloudinary():
    import cloudinary
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
        secure=True,
    )


def _public_id_from_url(url: str) -> str:
    """Extrai o public_id de um secure_url do Cloudinary."""
    # https://res.cloudinary.com/{cloud}/raw/upload/v{ver}/{public_id}
    m = re.search(r'/(?:raw|image|video)/upload/(?:v\d+/)?(.+)$', url)
    return m.group(1) if m else url


# ── upload ────────────────────────────────────────────────────────────────────

def upload_file(file_bytes: bytes, original_filename: str,
                folder: str = 'meudocmed') -> str:
    """
    Faz upload dos bytes e retorna um stored_id único.
    - Cloudinary: retorna o secure_url completo
    - Local:      retorna o nome do arquivo
    """
    ext = get_extension(original_filename)
    unique = uuid.uuid4().hex

    if _cloudinary_configured():
        import cloudinary.uploader
        _init_cloudinary()
        public_id = f'{folder}/{unique}.{ext}' if ext else f'{folder}/{unique}'
        result = cloudinary.uploader.upload(
            file_bytes,
            public_id=public_id,
            resource_type='raw',
            use_filename=False,
            overwrite=False,
        )
        logger.error("Cloudinary upload OK: url=%s", result.get('secure_url', 'NONE')[:80])
        return result['secure_url']   # ← guarda a URL completa
    else:
        stored_name = f'{unique}.{ext}' if ext else unique
        return stored_name


# ── leitura ───────────────────────────────────────────────────────────────────

def get_file_bytes(stored_id: str, upload_folder: str = None) -> bytes | None:
    """Retorna os bytes do arquivo ou None se não encontrado."""
    if _cloudinary_configured():
        import requests as req
        from cloudinary.utils import private_download_url
        _init_cloudinary()
        import cloudinary.api
        try:
            logger.error("FETCH stored_id[:80]=%s is_url=%s",
                         stored_id[:80], stored_id.startswith('https://'))
            public_id = (_public_id_from_url(stored_id)
                         if stored_id.startswith('https://') else stored_id)
            logger.error("FETCH public_id=%s", public_id)

            # 1a tentativa: Admin API (Basic Auth) para verificar existencia
            try:
                resource = cloudinary.api.resource(public_id, resource_type='raw')
                logger.error("FETCH admin_api found: url=%s", resource.get('secure_url', '')[:80])
                r = req.get(resource['secure_url'], timeout=30)
                logger.error("FETCH direct_status=%s", r.status_code)
                if r.status_code == 200:
                    return r.content
                api_key = os.environ.get('CLOUDINARY_API_KEY')
                api_secret = os.environ.get('CLOUDINARY_API_SECRET')
                r2 = req.get(resource['secure_url'],
                             auth=(api_key, api_secret), timeout=30)
                logger.error("FETCH basic_auth_status=%s", r2.status_code)
                if r2.status_code == 200:
                    return r2.content
            except Exception as api_exc:
                logger.error("FETCH admin_api_error=%s", str(api_exc)[:120])

            # 2a tentativa: private_download_url
            dl_url = private_download_url(public_id, '', resource_type='raw')
            logger.error("FETCH priv_dl_url[:80]=%s", dl_url[:80])
            r3 = req.get(dl_url, timeout=30)
            logger.error("FETCH priv_dl_status=%s body=%s", r3.status_code, r3.text[:120])
            if r3.status_code == 200:
                return r3.content
            return None
        except Exception as exc:
            logger.exception("Cloudinary get_file_bytes exception: %s", exc)
            return None
    else:
        folder = upload_folder or os.environ.get('UPLOAD_FOLDER', 'uploads')
        path = os.path.join(folder, stored_id)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
        return None


# ── exclusão ──────────────────────────────────────────────────────────────────

def delete_stored_file(stored_id: str, upload_folder: str = None) -> bool:
    """Remove o arquivo. Retorna True se apagado com sucesso."""
    if _cloudinary_configured():
        import cloudinary.uploader
        _init_cloudinary()
        try:
            public_id = (_public_id_from_url(stored_id)
                         if stored_id.startswith('https://') else stored_id)
            cloudinary.uploader.destroy(public_id, resource_type='raw')
            return True
        except Exception as exc:
            logger.exception("Cloudinary delete_stored_file exception: %s", exc)
            return False
    else:
        folder = upload_folder or os.environ.get('UPLOAD_FOLDER', 'uploads')
        path = os.path.join(folder, stored_id)
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
        except OSError:
            pass
        return False


# ── helper para PyMuPDF (precisa de arquivo em disco) ────────────────────────

class TempFile:
    """
    Context manager que baixa o arquivo para um temp e garante cleanup.

    Uso:
        with TempFile(doc.filename, upload_folder, ext='pdf') as path:
            pdf = fitz.open(path)
    """
    def __init__(self, stored_id: str, upload_folder: str = None, ext: str = ''):
        self.stored_id = stored_id
        self.upload_folder = upload_folder
        self.ext = ext
        self._tmp_path = None

    def __enter__(self) -> str:
        if _cloudinary_configured():
            data = get_file_bytes(self.stored_id)
            if not data:
                raise FileNotFoundError(f"Não foi possível baixar: {self.stored_id}")
            suffix = f'.{self.ext}' if self.ext else ''
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(data)
                self._tmp_path = f.name
            return self._tmp_path
        else:
            folder = self.upload_folder or os.environ.get('UPLOAD_FOLDER', 'uploads')
            return os.path.join(folder, self.stored_id)

    def __exit__(self, *_):
        if self._tmp_path and os.path.exists(self._tmp_path):
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
