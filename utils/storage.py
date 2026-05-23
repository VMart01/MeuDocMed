"""
utils/storage.py — Abstração de armazenamento de arquivos.

Em desenvolvimento (sem CLOUDINARY_CLOUD_NAME): salva/lê do disco local.
Em produção (com CLOUDINARY_CLOUD_NAME):        usa Cloudinary (resource_type=raw).

A interface pública é:
  upload_file(file_bytes, original_filename)  -> stored_id (str)
  get_file_bytes(stored_id, upload_folder)    -> bytes | None
  delete_stored_file(stored_id, upload_folder)-> bool
"""
import os
import io
import uuid
import tempfile

from utils.file_utils import get_extension


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


# ── upload ────────────────────────────────────────────────────────────────────

def upload_file(file_bytes: bytes, original_filename: str,
                folder: str = 'meudocmed') -> str:
    """
    Faz upload dos bytes e retorna um stored_id único.
    - Cloudinary: retorna o public_id  (ex: 'meudocmed/abc123def.pdf')
    - Local:      retorna o nome do arquivo (ex: 'abc123def.pdf')
    """
    ext = get_extension(original_filename)
    unique = uuid.uuid4().hex

    if _cloudinary_configured():
        import cloudinary.uploader
        _init_cloudinary()
        public_id = f'{folder}/{unique}'
        result = cloudinary.uploader.upload(
            file_bytes,
            public_id=public_id,
            resource_type='raw',       # sempre raw — sem transformações
            format=ext or None,
            use_filename=False,
            overwrite=False,
        )
        return result['public_id']     # ex: 'meudocmed/abc123.pdf'
    else:
        stored_name = f'{unique}.{ext}' if ext else unique
        return stored_name             # chamador salva no disco


# ── leitura ───────────────────────────────────────────────────────────────────

def get_file_bytes(stored_id: str, upload_folder: str = None) -> bytes | None:
    """Retorna os bytes do arquivo ou None se não encontrado."""
    if _cloudinary_configured():
        import cloudinary.utils
        import requests as req
        _init_cloudinary()
        url, _ = cloudinary.utils.cloudinary_url(
            stored_id, resource_type='raw', secure=True)
        try:
            r = req.get(url, timeout=15)
            return r.content if r.status_code == 200 else None
        except Exception:
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
            cloudinary.uploader.destroy(stored_id, resource_type='raw')
            return True
        except Exception:
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
            suffix = f'.{self.ext}' if self.ext else ''
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(data or b'')
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
