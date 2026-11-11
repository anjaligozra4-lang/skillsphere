from functools import lru_cache
import secrets
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SkillSphere"
    app_env: str = "development"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "skillsphere"
    mysql_password: str = ""
    mysql_database: str = "skillsphere_db"

    cors_origins: str = "http://localhost:5173"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    admin_email: str = "admin@skillsphere.com"
    admin_password: str = ""
    demo_recruiter_password: str = ""
    admin_full_name: str = "SkillSphere Administrator"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        if not self.mysql_password:
            return "sqlite:///./skillsphere.db"

        encoded_password = quote_plus(self.mysql_password)

        return (
            f"mysql+pymysql://{self.mysql_user}:{encoded_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if not value and cls.model_fields["jwt_secret_key"].default == "":
            return value
        return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    if settings.app_env == "production" and not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY is required in production.")

    if not settings.jwt_secret_key:
        settings.jwt_secret_key = secrets.token_urlsafe(48)

    return settings
