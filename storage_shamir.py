"""
storage_shamir.py — Armazenamento distribuído com Shamir's Secret Sharing (2-de-3)

Distribuição dos shards:
  Shard 1 + arquivo cifrado → Backblaze B2
  Shard 2                   → IDrive e2
  Shard 3                   → Cloudinary (resource_type=raw, pasta shards/)

Fluxo de upload:
  1. Gera senha aleatória (32 bytes) e salt (16 bytes)
  2. Deriva chave AES-256 via PBKDF2-HMAC-SHA256 (100 000 iterações)
  3. Cifra o arquivo com AES-256-GCM → nonce + tag + ciphertext (blob)
  4. Aplica Shamir 2-de-3 sobre a senha (byte a byte em GF(2^8))
  5. blob + shard1 → B2 | shard2 → IDrive | shard3 → Cloudinary
  6. Retorna dict com file_id, nonce_hex, salt_hex (storage_meta) — sem shard3_hex no DB

Fallback:
  Se B2 ou IDrive não estiverem configurados, retorna None.
  O Cloudinary já é obrigatório para produção (shard 3 e arquivo cifrado como backup).
"""

import hashlib
import logging
import os
import secrets
import uuid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GF(2^8) — polinômio irredutível do AES: x^8+x^4+x^3+x+1
# ---------------------------------------------------------------------------

def _gf_mul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _gf_inv(a):
    if a == 0:
        raise ZeroDivisionError
    result, base, exp = 1, a, 254
    while exp > 0:
        if exp & 1:
            result = _gf_mul(result, base)
        base = _gf_mul(base, base)
        exp >>= 1
    return result


# ---------------------------------------------------------------------------
# Shamir 2-de-3 em GF(2^8) — byte a byte
# ---------------------------------------------------------------------------

def _shamir_split(secret):
    s1, s2, s3 = bytearray(len(secret)), bytearray(len(secret)), bytearray(len(secret))
    for i, b in enumerate(secret):
        a1 = secrets.randbelow(254) + 1
        s1[i] = b ^ _gf_mul(a1, 1)
        s2[i] = b ^ _gf_mul(a1, 2)
        s3[i] = b ^ _gf_mul(a1, 3)
    return bytes(s1), bytes(s2), bytes(s3)


def _shamir_reconstruct(shares):
    assert len(shares) == 2
    (x0, y0), (x1, y1) = shares
    secret = bytearray(len(y0))
    for i in range(len(y0)):
        term0 = _gf_mul(y0[i], _gf_mul(x1, _gf_inv(x0 ^ x1)))
        term1 = _gf_mul(y1[i], _gf_mul(x0, _gf_inv(x1 ^ x0)))
        secret[i] = term0 ^ term1
    return bytes(secret)


# ---------------------------------------------------------------------------
# AES-256-GCM
# ---------------------------------------------------------------------------

def _aes_encrypt(key, plaintext):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    ct_and_tag = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce, ct_and_tag[:-16], ct_and_tag[-16:]


def _aes_decrypt(key, nonce, ciphertext, tag):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(nonce, ciphertext + tag, None)


def _derive_key(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password, salt, 100_000, dklen=32)


# ---------------------------------------------------------------------------
# Backblaze B2 (S3-compatible)
# ---------------------------------------------------------------------------

def _b2_configured():
    return bool(os.environ.get('B2_ACCESS_KEY_ID'))


def _b2_client():
    import boto3
    return boto3.client(
        's3',
        endpoint_url=os.environ['B2_ENDPOINT_URL'],
        aws_access_key_id=os.environ['B2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['B2_SECRET_ACCESS_KEY'],
        region_name=os.environ.get('B2_REGION', 'us-east-005'),
    )


def _b2_put(key, data):
    try:
        _b2_client().put_object(Bucket=os.environ.get('B2_BUCKET', 'meudocmed-shard-1'), Key=key, Body=data)
        return True
    except Exception as e:
        logger.exception("B2 put %s: %s", key, e)
        return False


def _b2_get(key):
    try:
        r = _b2_client().get_object(Bucket=os.environ.get('B2_BUCKET', 'meudocmed-shard-1'), Key=key)
        return r['Body'].read()
    except Exception as e:
        logger.exception("B2 get %s: %s", key, e)
        return None


def _b2_delete(key):
    try:
        _b2_client().delete_object(Bucket=os.environ.get('B2_BUCKET', 'meudocmed-shard-1'), Key=key)
        return True
    except Exception as e:
        logger.exception("B2 delete %s: %s", key, e)
        return False


# ---------------------------------------------------------------------------
# IDrive e2 (S3-compatible)
# ---------------------------------------------------------------------------

def _idrive_configured():
    return bool(os.environ.get('IDRIVE_ACCESS_KEY_ID'))


def _idrive_client():
    import boto3
    return boto3.client(
        's3',
        endpoint_url=os.environ['IDRIVE_ENDPOINT_URL'],
        aws_access_key_id=os.environ['IDRIVE_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['IDRIVE_SECRET_ACCESS_KEY'],
        region_name=os.environ.get('IDRIVE_REGION', 'us-west-4'),
    )


def _idrive_put(key, data):
    try:
        _idrive_client().put_object(Bucket=os.environ.get('IDRIVE_BUCKET', 'meudocmed-shard-2'), Key=key, Body=data)
        return True
    except Exception as e:
        logger.exception("IDrive put %s: %s", key, e)
        return False


def _idrive_get(key):
    try:
        r = _idrive_client().get_object(Bucket=os.environ.get('IDRIVE_BUCKET', 'meudocmed-shard-2'), Key=key)
        return r['Body'].read()
    except Exception as e:
        logger.exception("IDrive get %s: %s", key, e)
        return None


def _idrive_delete(key):
    try:
        _idrive_client().delete_object(Bucket=os.environ.get('IDRIVE_BUCKET', 'meudocmed-shard-2'), Key=key)
        return True
    except Exception as e:
        logger.exception("IDrive delete %s: %s", key, e)
        return False


# ---------------------------------------------------------------------------
# Cloudinary (shard 3 — resource_type=raw)
# ---------------------------------------------------------------------------

def _cloudinary_configured():
    return bool(os.environ.get('CLOUDINARY_CLOUD_NAME'))


def _init_cloudinary():
    import cloudinary
    cloudinary.config(
        cloud_name=os.environ['CLOUDINARY_CLOUD_NAME'],
        api_key=os.environ['CLOUDINARY_API_KEY'],
        api_secret=os.environ['CLOUDINARY_API_SECRET'],
        secure=True,
    )


def _cloudinary_put_shard(public_id, data):
    try:
        import cloudinary.uploader
        _init_cloudinary()
        cloudinary.uploader.upload(data, public_id=public_id, resource_type='raw',
                                   overwrite=True, use_filename=False)
        return True
    except Exception as e:
        logger.exception("Cloudinary shard put %s: %s", public_id, e)
        return False


def _cloudinary_get_shard(public_id):
    try:
        import requests as req
        from cloudinary.utils import cloudinary_url
        _init_cloudinary()
        url, _ = cloudinary_url(public_id, resource_type='raw', sign_url=True, secure=True)
        r = req.get(url, timeout=20)
        return r.content if r.status_code == 200 else None
    except Exception as e:
        logger.exception("Cloudinary shard get %s: %s", public_id, e)
        return None


def _cloudinary_delete_shard(public_id):
    try:
        import cloudinary.uploader
        _init_cloudinary()
        cloudinary.uploader.destroy(public_id, resource_type='raw')
        return True
    except Exception as e:
        logger.exception("Cloudinary shard delete %s: %s", public_id, e)
        return False


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def shamir_configured():
    return _b2_configured() and _idrive_configured() and _cloudinary_configured()


def clouds_status():
    b2_ok = idrive_ok = cloudinary_ok = False
    if _b2_configured():
        try:
            _b2_client().list_buckets()
            b2_ok = True
        except Exception:
            pass
    if _idrive_configured():
        try:
            _idrive_client().list_buckets()
            idrive_ok = True
        except Exception:
            pass
    if _cloudinary_configured():
        try:
            import cloudinary.api
            _init_cloudinary()
            cloudinary.api.ping()
            cloudinary_ok = True
        except Exception:
            pass
    return {
        'b2':        {'configured': _b2_configured(),         'reachable': b2_ok},
        'idrive':    {'configured': _idrive_configured(),      'reachable': idrive_ok},
        'cloudinary':{'configured': _cloudinary_configured(),  'reachable': cloudinary_ok},
        'shamir_ready': b2_ok and idrive_ok and cloudinary_ok,
    }


def upload_shamir(file_bytes, original_filename):
    """
    Cifra e distribui o arquivo.
    Retorna dict com file_id, ext, nonce_hex, salt_hex  — ou None em falha total.
    """
    try:
        from utils.file_utils import get_extension
        ext = get_extension(original_filename)
        file_id = uuid.uuid4().hex

        password = secrets.token_bytes(32)
        salt     = secrets.token_bytes(16)
        key      = _derive_key(password, salt)

        nonce, ciphertext, tag = _aes_encrypt(key, file_bytes)
        ct_blob = nonce + tag + ciphertext   # 12 + 16 + N bytes

        s1, s2, s3 = _shamir_split(password)

        file_key  = f'files/{file_id}.enc'
        shard_key = f'shards/{file_id}'

        ok_b2     = _b2_put(file_key, ct_blob) and _b2_put(shard_key, s1)
        ok_idrive = _idrive_put(shard_key, s2)
        ok_cld    = _cloudinary_put_shard(f'meudocmed/{shard_key}', s3)

        if not ok_b2:
            logger.error("upload_shamir: falhou no B2 — abortando")
            return None

        return {
            'file_id':   file_id,
            'ext':       ext,
            'nonce_hex': nonce.hex(),
            'salt_hex':  salt.hex(),
            'ok_b2':     ok_b2,
            'ok_idrive': ok_idrive,
            'ok_cld':    ok_cld,
        }
    except Exception as e:
        logger.exception("upload_shamir: %s", e)
        return None


def download_shamir(file_id, ext, nonce_hex, salt_hex):
    """Baixa e descriptografa o arquivo. Retorna bytes ou None."""
    try:
        file_key  = f'files/{file_id}.enc'
        shard_key = f'shards/{file_id}'

        ct_blob = _b2_get(file_key)
        if ct_blob is None:
            return None

        # Tenta reconstruir senha com qualquer 2 dos 3 shards
        s1 = _b2_get(shard_key)     if _b2_configured()         else None
        s2 = _idrive_get(shard_key) if _idrive_configured()      else None
        s3 = _cloudinary_get_shard(f'meudocmed/{shard_key}') if _cloudinary_configured() else None

        shares = None
        if s1 and s2:
            shares = [(1, s1), (2, s2)]
        elif s1 and s3:
            shares = [(1, s1), (3, s3)]
        elif s2 and s3:
            shares = [(2, s2), (3, s3)]

        if shares is None:
            logger.error("download_shamir: menos de 2 shards disponíveis para %s", file_id)
            return None

        password = _shamir_reconstruct(shares)
        key      = _derive_key(password, bytes.fromhex(salt_hex))
        nonce    = ct_blob[:12]
        tag      = ct_blob[12:28]
        cipher   = ct_blob[28:]

        return _aes_decrypt(key, nonce, cipher, tag)
    except Exception as e:
        logger.exception("download_shamir: %s", e)
        return None


def delete_shamir(file_id, ext):
    shard_key = f'shards/{file_id}'
    ok = True
    if _b2_configured():
        ok &= _b2_delete(f'files/{file_id}.enc')
        ok &= _b2_delete(shard_key)
    if _idrive_configured():
        ok &= _idrive_delete(shard_key)
    if _cloudinary_configured():
        ok &= _cloudinary_delete_shard(f'meudocmed/{shard_key}')
    return ok
