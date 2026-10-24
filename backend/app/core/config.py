"""Application settings, read from environment variables (see deploy/.env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "xaminer"
    postgres_user: str = "xaminer"
    postgres_password: SecretStr = SecretStr("")

    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    s3_endpoint: str = "http://localhost:8333"
    s3_access_key: str = ""
    s3_secret_key: SecretStr = SecretStr("")

    smtp_host: str = "localhost"
    smtp_port: int = 1025

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
