import hashlib
import hmac
import secrets

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
