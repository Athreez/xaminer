"""Shared settings for tests that call the real HTTP API against the test database and Redis."""

from app.core.config import Settings
from tests.db.conftest import PORT, TEST_DB
from tests.services import ENV, HOST

PASSWORD = "violet-tram-42-lantern"
SECRET = "test-signing-secret-that-is-long-enough-123"
REDIS_PORT = int(ENV.get("TEST_REDIS_PORT", ENV.get("REDIS_HOST_PORT", "16379")))


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "postgres_host": HOST,
        "postgres_port": PORT,
        "postgres_db": TEST_DB,
        "db_app_password": ENV.get("DB_APP_PASSWORD", ""),
        # Database 15 keeps test keys (rate limits) away from the real ones in database 0.
        "redis_url": f"redis://:{ENV.get('REDIS_PASSWORD', '')}@{HOST}:{REDIS_PORT}/15",
        "jwt_secret": SECRET,
        "cookie_secure": False,  # the test client talks plain http
        "public_base_url": "http://xaminer.test",
        # Every test request comes from the same fake address; the limit test sets its own.
        "login_rate_per_minute": 10_000,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]
