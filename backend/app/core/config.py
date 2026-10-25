"""Application settings, read from environment variables (see deploy/.env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "xaminer"
    # Two DB users (SECURITY_AND_ACCESS.md § 5.6). The app never gets the migrator password.
    db_app_user: str = "app"
    db_app_password: SecretStr = SecretStr("")
    db_migrator_user: str = "migrator"
    db_migrator_password: SecretStr = SecretStr("")

    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    s3_endpoint: str = "http://localhost:8333"
    s3_access_key: str = ""
    s3_secret_key: SecretStr = SecretStr("")

    smtp_host: str = "localhost"
    smtp_port: int = 1025

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"

    def database_url(self, role: Literal["app", "migrator"] = "app") -> URL:
        user, password = (
            (self.db_app_user, self.db_app_password)
            if role == "app"
            else (self.db_migrator_user, self.db_migrator_password)
        )
        return URL.create(
            "postgresql+asyncpg",
            username=user,
            password=password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
