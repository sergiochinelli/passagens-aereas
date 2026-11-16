import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_ALGORITHM = "sha256"


def hash_password(password: str) -> str:
    """Gera hash PBKDF2-HMAC-SHA256 no formato iterations$salt$hash."""
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        _ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        settings.PBKDF2_ITERATIONS,
    )
    return f"{settings.PBKDF2_ITERATIONS}${salt}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        iterations, salt, expected = stored_hash.split("$")
        derived = hashlib.pbkdf2_hmac(
            _ALGORITHM,
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        )
        return hmac.compare_digest(derived.hex(), expected)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Formato legado "v1.<b64iv>.<b64ct>" — AES-GCM gerado no frontend (crypto.subtle).
# A chave deriva de AUTH_MASTER_KEY + AUTH_V1_SALT via PBKDF2-SHA256. Mantido
# apenas para validar senhas gravadas pelo frontend antigo; senhas novas sao
# sempre escritas em PBKDF2 (nao reversivel).
# ---------------------------------------------------------------------------


def _v1_key() -> bytes:
    return hashlib.pbkdf2_hmac(
        _ALGORITHM,
        settings.AUTH_MASTER_KEY.encode("utf-8"),
        settings.AUTH_V1_SALT.encode("utf-8"),
        settings.AUTH_V1_ITERATIONS,
        dklen=32,
    )


def encrypt_v1_password(password: str) -> str:
    """Cifra no formato legado `v1.<b64iv>.<b64ct>` (usado em seeds/testes)."""
    iv = secrets.token_bytes(12)
    ciphertext = AESGCM(_v1_key()).encrypt(iv, password.encode("utf-8"), None)
    return f"v1.{base64.b64encode(iv).decode()}.{base64.b64encode(ciphertext).decode()}"


def decrypt_v1_password(stored: str) -> str | None:
    """Decifra `v1.<b64iv>.<b64ct>`. Retorna None em qualquer falha."""
    try:
        _, iv_b64, ct_b64 = stored.split(".")
        plaintext = AESGCM(_v1_key()).decrypt(
            base64.b64decode(iv_b64), base64.b64decode(ct_b64), None
        )
        return plaintext.decode("utf-8")
    except Exception:
        return None


def verify_any_password(password: str, stored: str) -> bool:
    """Verifica senha em qualquer formato suportado (v1 legado ou PBKDF2)."""
    if stored.startswith("v1."):
        plaintext = decrypt_v1_password(stored)
        return plaintext is not None and hmac.compare_digest(plaintext, password)
    return verify_password(password, stored)


# ---------------------------------------------------------------------------
# Sessoes: token opaco (apenas o hash SHA-256 e persistido)
# ---------------------------------------------------------------------------


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
