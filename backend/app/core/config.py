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
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = False  # turn on for a real SMTP server (e.g. port 587)
    mail_from: str = "Xaminer <no-reply@xaminer.local>"
    # Where users open the app; used to build links in emails.
    public_base_url: str = "http://localhost:8080"

    # Login tokens (SECURITY_AND_ACCESS.md § 2.2). The secret signs access tokens: keep it private,
    # at least 32 characters. Changing it logs everyone out.
    jwt_secret: SecretStr = SecretStr("")
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # Send the refresh cookie only over HTTPS. Browsers treat http://localhost as secure too.
    cookie_secure: bool = True
    # Login attempts allowed per IP address per minute (PRD AUTH-06).
    login_rate_per_minute: int = 10

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"

    def check_secrets(self) -> None:
        """Refuse to start with a missing or weak signing secret (called when the API starts)."""
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32 or secret.startswith("change-me"):
            raise RuntimeError(
                "JWT_SECRET must be a random value of at least 32 characters "
                "(not the placeholder from .env.example)."
            )

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
