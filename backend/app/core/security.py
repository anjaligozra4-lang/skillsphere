from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from jose import jwt
from passlib.context import CryptContext

from app.core.config import get_settings


password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def isoformat_utc(dt: datetime | None) -> str | None:
    normalized = ensure_utc(dt)
    return normalized.isoformat() if normalized else None


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_context.verify(password, password_hash)


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    expires = utc_now() + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": subject, "role": role, "type": "access", "exp": expires},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token_value() -> str:
    return secrets.token_urlsafe(48)


def hash_opaque_token(token: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str, salt: str) -> str:
    settings = get_settings()
    message = f"{salt}:{otp}".encode("utf-8")
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def verify_otp_hash(otp: str, salt: str, expected_hash: str) -> bool:
    computed = hash_otp(otp, salt)
    return hmac.compare_digest(computed, expected_hash)
