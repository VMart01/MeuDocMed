"""
Utilitários de arquivo: validação por magic number, geração de nomes únicos,
e determinação do tipo MIME para servir arquivos.
"""
import os
import uuid
import mimetypes

# Magic numbers (primeiros bytes) por extensão
MAGIC_NUMBERS = {
    'pdf':  (b'%PDF',),
    'png':  (b'\x89PNG\r\n\x1a\n',),
    'jpg':  (b'\xff\xd8\xff',),
    'jpeg': (b'\xff\xd8\xff',),
    'gif':  (b'GIF87a', b'GIF89a'),
    'bmp':  (b'BM',),
    # WEBP: RIFF????WEBP
    'webp': None,  # verificação especial
    # DOCX e XLSX são ZIP internamente
    'docx': (b'PK\x03\x04',),
    'xlsx': (b'PK\x03\x04',),
    # DOC/XLS antigos: OLE2
    'doc':  (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
    'xls':  (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
    # ZIP
    'zip':  (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'),
    # TXT: sem magic number fixo — tentamos decodificar como UTF-8
    'txt':  None,
}

ALLOWED_EXTENSIONS = {
    'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
    'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip',
}


def allowed_extension(filename: str) -> bool:
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def get_extension(filename: str) -> str:
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''


def validate_magic_number(file_bytes: bytes, ext: str) -> bool:
    """
    Verifica se os primeiros bytes do arquivo correspondem ao magic number
    esperado para a extensão declarada.
    """
    ext = ext.lower()

    if ext not in MAGIC_NUMBERS:
        return False  # extensão não reconhecida

    if ext == 'txt':
        # TXT: basta decodificar sem erro
        try:
            file_bytes[:4096].decode('utf-8')
            return True
        except UnicodeDecodeError:
            try:
                file_bytes[:4096].decode('latin-1')
                return True
            except Exception:
                return False

    if ext == 'webp':
        # RIFF????WEBP
        return (
            len(file_bytes) >= 12 and
            file_bytes[:4] == b'RIFF' and
            file_bytes[8:12] == b'WEBP'
        )

    magic_list = MAGIC_NUMBERS.get(ext)
    if magic_list is None:
        return True  # sem verificação

    return any(file_bytes[:len(m)] == m for m in magic_list)


def generate_unique_filename(original_filename: str) -> str:
    """Gera um nome único para armazenamento seguro, preservando a extensão."""
    ext = get_extension(original_filename)
    unique_name = uuid.uuid4().hex
    return f'{unique_name}.{ext}' if ext else unique_name


def get_mime_type(filename: str) -> str:
    """Retorna o MIME type para o arquivo."""
    ext = get_extension(filename)
    mime_map = {
        'pdf': 'application/pdf',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
        'webp': 'image/webp',
        'txt': 'text/plain',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'zip': 'application/zip',
    }
    return mime_map.get(ext, 'application/octet-stream')


def is_viewable_inline(filename: str) -> bool:
    """Retorna True se o arquivo pode ser exibido inline no navegador."""
    ext = get_extension(filename)
    return ext in {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'txt'}


def delete_file(upload_folder: str, stored_filename: str) -> bool:
    """Remove o arquivo físico do servidor. Retorna True se removido."""
    path = os.path.join(upload_folder, stored_filename)
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except OSError:
        pass
    return False
