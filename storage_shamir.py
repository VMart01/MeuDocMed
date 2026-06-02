"""
storage_shamir.py — Armazenamento distribuído com Shamir's Secret Sharing (2-de-3)

Fluxo de upload:
  1. Gera senha aleatória (32 bytes) e salt (16 bytes)
  2. Deriva chave AES-256 via PBKDF2-HMAC-SHA256 (100 000 iterações)
  3. Cifra o arquivo com AES-256-GCM → nonce + tag + ciphertext
  4. Aplica Shamir 2-de-3 sobre a senha (byte a byte em GF(2^8))
  5. Encrypted blob → B2  (object_key: files/{file_id}.enc)
     Shard 1           → B2  (object_key: shards/{file_id})
     Shard 2           → IDrive e2
     Shard 3           → retornado como shard3_hex para salvar no PostgreSQL
  6. Retorna dict com file_id, nonce_hex, salt_hex, shard3_hex, ok_b2, ok_idrive

Fluxo de download:
  Tenta recuperar arquivo cifrado do B2.
  Reconstrói senha com qualquer 2 dos 3 shards.
  Deriva chave e descriptografa.

Fallback:
  Se B2 e IDrive não estiverem configurados, retorna None
  (a camada superior deve usar armazenamento local ou Cloudinary).
"""

import hashlib
import json
import logging
import os
import secrets
import uuid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GF(2^8) – polinômio irredutível do AES: x^8+x^4+x^3+x+1
# ---------------------------------------------------------------------------

def _gf_mul(a: int, b: int) -> int:
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


def _gf_inv(a: int) -> int:
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
# Shamir 2-de-3 sobre GF(2^8) — byte a byte
# ---------------------------------------------------------------------------

def _shamir_split(secret: bytes) -> tuple:
    """Retorna (shard1, shard2, shard3) — cada um com len(secret) bytes."""
    s1, s2, s3 = bytearray(len(secret)), bytearray(len(secret)), bytearray(len(secret))
    for i, b in enumerate(secret):
        a1 = secrets.randbelow(254) + 1   # a1 in [1, 254]
        s1[i] = b ^ _gf_mul(a1, 1)
        s2[i] = b ^ _gf_mul(a1, 2)
        s3[i] = b ^ _gf_mul(a1, 3)
    return bytes(s1), bytes(s2), bytes(s3)


def _shamir_reconstruct(shares: list) -> bytes:
    """
    Reconstrói o segredo a partir de 2 shares.
    shares: lista de (x, bytes) onde x in {1, 2, 3}.
    """
    assert len(shares) == 2
    (x0, y0), (x1, y1) = shares
    n = len(y0)
    secret = bytearray(n)
    for i in range(n):
        # Lagrange em f(0) = b XOR gf_mul(a1, 0) = b
        # num0 = 0 XOR x1 = x1, den0 = x0 XOR x1
        term0 = _gf_mul(y0[i], _gf_mul(x1, _gf_inv(x0 ^ x1)))
        term1 = _gf_mul(y1[i], _gf_mul(x0, _gf_inv(x1 ^ x0)))
        secret[i] = term0 ^ term1
    return bytes(secret)


# ---------------------------------------------------------------------------
# AES-256-GCM
# ---------------------------------------------------------------------------

def _aes_encrypt(key: bytes, plaintext: bytes) -> tuple:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    ct_and_tag = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce, ct_and_tag[:-16], ct_and_tag[-16:]


def _aes_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(nonce, ciphertext + tag, None)


def _derive_key(password: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password, salt, 100_000, dklen=32)


# ---------------------------------------------------------------------------
# Clientes S3-compatible
# ---------------------------------------------------------------------------

def _b2_configured() -> bool:
    return bool(os.environ.get('B2_ACCESS_KEY_ID'))


def _idrive_configured() -> bool:
    return bool(os.environ.get('IDRIVE_ACCESS_KEY_ID'))


def _s3_client(provider: str):
    import boto3
    if provider == 'b2':
        return boto3.client(
            's3',
            endpoint_url=os.environ['B2_ENDPOINT_URL'],
            aws_access_key_id=os.environ['B2_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['B2_SECRET_ACCESS_KEY'],
            region_name=os.environ.get('B2_REGION', 'us-east-005'),
        )
    else:
        return boto3.client(
            's3',
            endpoint_url=os.environ['IDRIVE_ENDPOINT_URL'],
            aws_access_key_id=os.environ['IDRIVE_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['IDRIVE_SECRET_ACCESS_KEY'],
            region_name=os.environ.get('IDRIVE_REGION', 'us-west-4'),
        )


def _b2_put(key: str, data: bytes) -> bool:
    try:
        _s3_client('b2').put_object(
            Bucket=os.environ.get('B2_BUCKET', 'meudocmed-shard-1'),
            Key=key, Body=data)
        return True
    except Exception as e:
        logger.exception("B2 put %s: %s", key, e)
        return False


def _b2_get(key: str) -> bytes | None:
    try:
        resp = _s3_client('b2').get_object(
            Bucket=os.environ.get('B2_BUCKET', 'meudocmed-shard-1'), Key=key)
        return resp['Body'].read()
    except Exception as e:
        logger.exception("B2 get %s: %s", key, e)
        return None


def _b2_delete(key: str) -> bool:
    try:
        _s3_client('b2').delete_object(
            Bucket=os.environ.get('B2_BUCKET', 'meudocmed-shard-1'), Key=key)
        return True
    except Exception as e:
        logger.exception("B2 delete %s: %s", key, e)
        return False


def _idrive_put(key: str, data: bytes) -> bool:
    try:
        _s3_client('idrive').put_object(
            Bucket=os.environ.get('IDRIVE_BUCKET', 'meudocmed-shard-2'),
            Key=key, Body=data)
        return True
    except Exception as e:
        logger.exception("IDrive put %s: %s", key, e)
        return False


def _idrive_get(key: str) -> bytes | None:
    try:
        resp = _s3_client('idrive').get_object(
            Bucket=os.environ.get('IDRIVE_BUCKET', 'meudocmed-shard-2'), Key=key)
        return resp['Body'].read()
    except Exception as e:
        logger.exception("IDrive get %s: %s", key, e)
        return None


def _idrive_delete(key: str) -> bool:
    try:
        _s3_client('idrive').delete_object(
            Bucket=os.environ.get('IDRIVE_BUCKET', 'meudocmed-shard-2'), Key=key)
        return True
    except Exception as e:
        logger.exception("IDrive delete %s: %s", key, e)
        return False


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def shamir_configured() -> bool:
    return _b2_configured() and _idrive_configured()


def clouds_status() -> dict:
    """Retorna status de cada cloud — para rota de diagnóstico."""
    b2_ok = False
    idrive_ok = False

    if _b2_configured():
        try:
            _s3_client('b2').list_buckets()
            b2_ok = True
        except Exception:
            pass

    if _idrive_configured():
        try:
            _s3_client('idrive').list_buckets()
            idrive_ok = True
        except Exception:
            pass

    return {
        'b2': {'configured': _b2_configured(), 'reachable': b2_ok},
        'idrive': {'configured': _idrive_configured(), 'reachable': idrive_ok},
        'shamir_ready': b2_ok and idrive_ok,
    }


def upload_shamir(file_bytes: bytes, original_filename: str) -> dict | None:
    """
    Cifra e distribui o arquivo.
    Retorna dict ou None em caso de falha total.

    Dict retornado:
      file_id    — identificador único (str)
      ext        — extensão do arquivo
      nonce_hex  — nonce do AES (str)
      salt_hex   — salt do PBKDF2 (str)
      shard3_hex — shard 3 para salvar no PostgreSQL (str)
      ok_b2      — bool
      ok_idrive  — bool
    """
    try:
        from utils.file_utils import get_extension
        ext = get_extension(original_filename)
        file_id = uuid.uuid4().hex

        # Chave
        password = secrets.token_bytes(32)
        salt = secrets.token_bytes(16)
        key = _derive_key(password, salt)

        # Cifragem
        nonce, ciphertext, tag = _aes_encrypt(key, file_bytes)
        ct_blob = nonce + tag + ciphertext   # 12 + 16 + len(file) bytes

        # Shamir sobre a senha (32 bytes → 3 × 32 bytes)
        s1, s2, s3 = _shamir_split(password)

        file_key = f'files/{file_id}.enc'
        shard_key = f'shards/{file_id}'

        # Upload: arquivo cifrado + shard1 → B2
        ok_b2 = False
        if _b2_configured():
            ok_blob = _b2_put(file_key, ct_blob)
            ok_s1   = _b2_put(shard_key, s1)
            ok_b2 = ok_blob and ok_s1

        # Shard 2 → IDrive
        ok_idrive = _idrive_put(shard_key, s2) if _idrive_configured() else False

        # Precisa do blob em B2 para download; sem B2 não faz sentido prosseguir
        if not ok_b2:
            logger.error("upload_shamir: falhou no B2 — arquivo não armazenado")
            return None

        return {
            'file_id': file_id,
            'ext': ext,
            'nonce_hex': nonce.hex(),
            'salt_hex': salt.hex(),
            'shard3_hex': s3.hex(),
            'ok_b2': ok_b2,
            'ok_idrive': ok_idrive,
        }

    except Exception as exc:
        logger.exception("upload_shamir exception: %s", exc)
        return None


def download_shamir(file_id: str, ext: str, nonce_hex: str,
                    salt_hex: str, shard3_hex: str) -> bytes | None:
    """
    Reconstrói e descriptografa o arquivo.
    """
    try:
        file_key  = f'files/{file_id}.enc'
        shard_key = f'shards/{file_id}'

        # Arquivo cifrado vem do B2
        ct_blob = _b2_get(file_key)
        if ct_blob is None:
            logger.error("download_shamir: arquivo não encontrado no B2 (%s)", file_id)
            return None

        # Reconstrói senha com 2 shards (tenta B2_shard1 + IDrive_shard2 primeiro)
        s3 = bytes.fromhex(shard3_hex)
        shares = None

        s1 = _b2_get(shard_key) if _b2_configured() else None
        if s1 is not None:
            shares = [(1, s1), (3, s3)]
        else:
            s2 = _idrive_get(shard_key) if _idrive_configured() else None
            if s2 is not None:
                shares = [(2, s2), (3, s3)]

        if shares is None:
            logger.error("download_shamir: nenhum shard de nuvem disponível para %s", file_id)
            return None

        password = _shamir_reconstruct(shares)
        key = _derive_key(password, bytes.fromhex(salt_hex))

        nonce      = ct_blob[:12]
        tag        = ct_blob[12:28]
        ciphertext = ct_blob[28:]

        return _aes_decrypt(key, nonce, ciphertext, tag)

    except Exception as exc:
        logger.exception("download_shamir exception: %s", exc)
        return None


def delete_shamir(file_id: str, ext: str) -> bool:
    file_key  = f'files/{file_id}.enc'
    shard_key = f'shards/{file_id}'
    ok = True
    if _b2_configured():
        ok &= _b2_delete(file_key)
        ok &= _b2_delete(shard_key)
    if _idrive_configured():
        ok &= _idrive_delete(shard_key)
    return ok
