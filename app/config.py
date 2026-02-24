from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "MMC Notice Board API"
    api_prefix: str = "/api"

    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 24 * 60

    database_url: str = Field(
        default=f"sqlite:///{(BASE_DIR / 'mmc.db').as_posix()}",
        alias="DATABASE_URL",
    )
    r2_endpoint: str = Field(default="", alias="R2_ENDPOINT")
    r2_access_key_id: str = Field(
        default="",
        validation_alias=AliasChoices("R2_ACCESS_KEY_ID", "R2_ACCESS_KEY"),
    )
    r2_secret_access_key: str = Field(
        default="",
        validation_alias=AliasChoices("R2_SECRET_ACCESS_KEY", "R2_SECRET_KEY"),
    )
    r2_bucket: str = Field(default="", alias="R2_BUCKET")
    r2_public_url: str = Field(default="", alias="R2_PUBLIC_URL")
    upload_dir: str = str(BASE_DIR / "uploads")
    notice_source_dir: str = str(BASE_DIR.parent / "frontend" / "data files" / "Notice")

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    cors_allow_origin_regex: str | None = Field(
        default=r"^https://.+$",
        alias="CORS_ALLOW_ORIGIN_REGEX",
    )

    admin_username: str = "admin"
    admin_password: str = "admin123"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_allow_origin_regex", mode="before")
    @classmethod
    def parse_cors_allow_origin_regex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator(
        "r2_endpoint",
        "r2_access_key_id",
        "r2_secret_access_key",
        "r2_bucket",
        "r2_public_url",
        mode="before",
    )
    @classmethod
    def parse_optional_text(cls, value: str | None) -> str:
        if value is None:
            return ""
        return value.strip()

    @field_validator("r2_endpoint", "r2_public_url", mode="after")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


settings = Settings()
