from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    APP_NAME: str = Field(
        default="Magadh Mahila College Backend",
        validation_alias=AliasChoices("APP_NAME", "PROJECT_NAME"),
    )
    API_PREFIX: str = "/api"
    ADMIN_PREFIX: str = "/admin"
    DATABASE_URL: str = "sqlite:///./mmc.db"

    JWT_SECRET_KEY: str = Field(
        default="change-this-secret-in-production",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])
    CORS_ALLOW_ORIGIN_REGEX: str | None = None

    UPLOAD_DIR: str = "uploads"
    NOTICE_SOURCE_DIR: str = "../frontend/data files/Notice"

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"
    DEFAULT_ADMIN_EMAIL: str = "admin@college.edu"
    DEFAULT_ADMIN_PASSWORD: str = "Admin@123"

    R2_ENDPOINT: str | None = None
    R2_ACCESS_KEY_ID: str | None = Field(
        default=None,
        validation_alias=AliasChoices("R2_ACCESS_KEY_ID", "R2_ACCESS_KEY"),
    )
    R2_SECRET_ACCESS_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("R2_SECRET_ACCESS_KEY", "R2_SECRET_KEY"),
    )
    R2_BUCKET: str | None = None
    R2_PUBLIC_URL: str | None = None

    AUTO_CREATE_TABLES: bool = True

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def app_name(self) -> str:
        return self.APP_NAME

    @property
    def api_prefix(self) -> str:
        return self.API_PREFIX

    @property
    def admin_prefix(self) -> str:
        return self.ADMIN_PREFIX

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

    @property
    def secret_key(self) -> str:
        return self.JWT_SECRET_KEY

    @property
    def algorithm(self) -> str:
        return self.JWT_ALGORITHM

    @property
    def access_token_expire_minutes(self) -> int:
        return self.ACCESS_TOKEN_EXPIRE_MINUTES

    @property
    def cors_origins(self) -> list[str]:
        return self.CORS_ORIGINS

    @property
    def cors_allow_origin_regex(self) -> str | None:
        return self.CORS_ALLOW_ORIGIN_REGEX

    @property
    def upload_dir(self) -> str:
        return self.UPLOAD_DIR

    @property
    def notice_source_dir(self) -> str:
        return self.NOTICE_SOURCE_DIR

    @property
    def admin_username(self) -> str:
        return self.ADMIN_USERNAME

    @property
    def admin_password(self) -> str:
        return self.ADMIN_PASSWORD

    @property
    def default_admin_email(self) -> str:
        return self.DEFAULT_ADMIN_EMAIL

    @property
    def default_admin_password(self) -> str:
        return self.DEFAULT_ADMIN_PASSWORD

    @property
    def r2_endpoint(self) -> str | None:
        return self.R2_ENDPOINT

    @property
    def r2_access_key_id(self) -> str | None:
        return self.R2_ACCESS_KEY_ID

    @property
    def r2_secret_access_key(self) -> str | None:
        return self.R2_SECRET_ACCESS_KEY

    @property
    def r2_bucket(self) -> str | None:
        return self.R2_BUCKET

    @property
    def r2_public_url(self) -> str | None:
        return self.R2_PUBLIC_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
