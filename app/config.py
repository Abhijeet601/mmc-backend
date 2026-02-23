from pathlib import Path

from pydantic import Field, field_validator
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
    upload_dir: str = str(BASE_DIR / "uploads")
    notice_source_dir: str = str(BASE_DIR.parent / "frontend" / "data files" / "Notice")

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

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


settings = Settings()
