import os
from pathlib import Path
import secrets
import threading
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
BACKEND_ENV_FILE = BACKEND_DIR / ".env"


DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "https://skillsphere-xi-mocha.vercel.app",
    "https://skillsphere-i9pr5t3gw-anjaligozra4-langs-projects.vercel.app",
)


class Settings(BaseSettings):
    app_name: str = "SkillSphere"
    app_env: str = "development"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "skillsphere"
    mysql_password: str = ""
    mysql_database: str = "skillsphere_db"

    cors_origins: str = (
        "http://localhost:5174,"
        "http://127.0.0.1:5174,"
        "https://skillsphere-xi-mocha.vercel.app,"
        "https://skillsphere-i9pr5t3gw-anjaligozra4-langs-projects.vercel.app"
    )
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    admin_email: str = "admin@skillsphere.com"
    admin_password: str = ""
    demo_recruiter_password: str = ""
    admin_full_name: str = "SkillSphere Administrator"

    # OTP Security settings
    otp_expire_minutes: int = 5
    otp_resend_cooldown_seconds: int = 30
    otp_max_attempts: int = 5

    # SMTP Email configuration
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "SkillSphere"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    # Frontend URL & Assessment settings
    frontend_base_url: str = "http://localhost:5174"
    assessment_duration_minutes: int = 30
    assessment_link_expire_hours: int = 72
    auto_shortlist_threshold: float = 70.0

    # Optional External AI Provider for test generation / matching enhancement
    ai_provider: str = "none"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_require_external: bool = False

    # Database URL override (e.g. for PostgreSQL on Render)
    database_url_override: str = Field(
        default="",
        validation_alias=AliasChoices(
            "database_url_override",
            "DATABASE_URL_OVERRIDE",
            "database_url",
            "DATABASE_URL",
        ),
    )

    # Cloudinary recording storage
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # LiveKit real-time communication & Egress
    livekit_url: str = "http://127.0.0.1:7880"
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_egress_staging_dir: str = ""

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        override = (
            self.database_url_override
            or os.environ.get("DATABASE_URL_OVERRIDE", "").strip()
            or os.environ.get("DATABASE_URL", "").strip()
        )
        if override:
            url = override
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            return url

        is_production = (
            self.app_env.lower() in ("production", "prod", "staging")
            or bool(os.getenv("RENDER"))
            or bool(os.getenv("RENDER_SERVICE_ID"))
        )
        if is_production:
            raise RuntimeError(
                "DATABASE_URL or DATABASE_URL_OVERRIDE environment variable is required in production. "
                "SkillSphere cannot connect to local MySQL (127.0.0.1:3306) or SQLite on Render."
            )

        if not self.mysql_password:
            return "sqlite:///./skillsphere.db"

        encoded_password = quote_plus(self.mysql_password)

        return (
            f"mysql+pymysql://{self.mysql_user}:{encoded_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @property
    def allowed_origins(self) -> list[str]:
        origins = {origin.rstrip("/") for origin in DEFAULT_ALLOWED_ORIGINS}
        for origin in self.cors_origins.split(","):
            cleaned = origin.strip().rstrip("/")
            if cleaned:
                origins.add(cleaned)
        if self.frontend_base_url and self.frontend_base_url.strip():
            origins.add(self.frontend_base_url.strip().rstrip("/"))
        return sorted(list(origins))

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if not value and cls.model_fields["jwt_secret_key"].default == "":
            return value
        return value


_settings_lock = threading.Lock()
_cached_settings: Settings | None = None
_cached_env_signature: tuple[tuple[str, int | None, int | None], ...] | None = None
_fallback_jwt_secret: str | None = None


def _configured_env_files() -> tuple[str, ...]:
    cwd_env = Path.cwd() / ".env"
    try:
        if cwd_env.resolve() != BACKEND_ENV_FILE.resolve() and cwd_env.is_file():
            return (str(BACKEND_ENV_FILE), str(cwd_env))
    except OSError:
        pass
    return (str(BACKEND_ENV_FILE),)


def _env_signature() -> tuple[tuple[str, int | None, int | None], ...]:
    candidates = [BACKEND_ENV_FILE]
    cwd_env = Path.cwd() / ".env"
    try:
        if cwd_env.resolve() != BACKEND_ENV_FILE.resolve():
            candidates.append(cwd_env)
    except OSError:
        pass

    signature: list[tuple[str, int | None, int | None]] = []
    for path in candidates:
        try:
            if path.is_file():
                stat_result = path.stat()
                signature.append((str(path), stat_result.st_mtime_ns, stat_result.st_size))
            else:
                signature.append((str(path), None, None))
        except OSError:
            signature.append((str(path), None, None))
    return tuple(signature)


def _clear_settings_cache() -> None:
    global _cached_settings, _cached_env_signature
    with _settings_lock:
        _cached_settings = None
        _cached_env_signature = None


def get_settings() -> Settings:
    """Return cached application settings, reloading automatically when .env changes."""
    global _cached_settings, _cached_env_signature, _fallback_jwt_secret
    current_sig = _env_signature()
    if _cached_settings is not None and _cached_env_signature == current_sig:
        return _cached_settings

    with _settings_lock:
        current_sig = _env_signature()
        if _cached_settings is not None and _cached_env_signature == current_sig:
            return _cached_settings

        settings = Settings(_env_file=_configured_env_files())

        is_production = (
            settings.app_env.lower() in ("production", "prod", "staging")
            or bool(os.getenv("RENDER"))
            or bool(os.getenv("RENDER_SERVICE_ID"))
        )
        if is_production and not settings.jwt_secret_key:
            raise RuntimeError("JWT_SECRET_KEY is required in production.")

        if not settings.jwt_secret_key:
            if _fallback_jwt_secret is None:
                _fallback_jwt_secret = secrets.token_urlsafe(48)
            settings.jwt_secret_key = _fallback_jwt_secret

        _cached_settings = settings
        _cached_env_signature = current_sig
        return settings


get_settings.cache_clear = _clear_settings_cache  # type: ignore[attr-defined]
