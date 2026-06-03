"""Security utilities — password hashing + JWT issue/verify."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt

from src.config.settings import settings

# bcrypt accepts at most 72 bytes — we enforce at the Pydantic boundary too.
_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    """Bcrypt-hash a plaintext password. Raises if password exceeds 72 bytes."""
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > _MAX_PASSWORD_BYTES:
        raise ValueError("password too long (max 72 bytes)")
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify plaintext against bcrypt hash. False on any error (including bad hash format)."""
    try:
        pw_bytes = plain.encode("utf-8")
        if len(pw_bytes) > _MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return jwt.encode(
        {"sub": subject, "role": role, "exp": expire, "type": "access", "jti": str(uuid4())},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "refresh", "jti": str(uuid4())},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """Decode + validate a JWT. Raises ValueError on any failure (expired, bad signature, malformed)."""
    try:
        return jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise ValueError("invalid token") from exc
