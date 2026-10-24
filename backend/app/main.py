"""FastAPI application. Run with: uvicorn app.main:app"""

from fastapi import FastAPI

from app.core import health
from app.core.config import Settings, get_settings
from app.core.errors import UnhandledErrorMiddleware, register_error_handlers
from app.core.logging import AccessLogMiddleware, configure_logging
from app.core.request_id import RequestIdMiddleware

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Xaminer API",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if settings.docs_enabled else None,
        redoc_url=None,
    )

    register_error_handlers(app)
    # Added innermost first. Request flows: RequestId -> AccessLog -> UnhandledError -> routes,
    # so the request ID exists for both the access log and any 500 response.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
