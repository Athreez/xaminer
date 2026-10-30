"""FastAPI application. Run with: uvicorn app.main:app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.attempts.router import attempts_router, runs_router, submissions_router
from app.attempts.router import router as student_exams_router
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.authz.guards import assert_routes_declared
from app.core import health
from app.core.config import Settings, get_settings
from app.core.errors import UnhandledErrorMiddleware, register_error_handlers
from app.core.logging import AccessLogMiddleware, configure_logging
from app.core.request_id import RequestIdMiddleware
from app.core.storage import Storage
from app.db.session import create_engine, create_session_factory
from app.exams.router import admin_router as admin_exams_router
from app.exams.router import router as exams_router
from app.images.router import router as images_router
from app.platform.settings import router as settings_router
from app.questions.router import languages_router
from app.questions.router import router as questions_router
from app.users.router import groups_router
from app.users.router import router as users_router

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.check_secrets()  # refuse to start without a proper signing secret
        engine = create_engine(settings.database_url("app"))
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = Redis.from_url(settings.redis_url.get_secret_value())
        yield
        await app.state.redis.aclose()
        await engine.dispose()

    app = FastAPI(
        title="Xaminer API",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if settings.docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.storage = Storage(settings)  # no connection is made until it's used

    register_error_handlers(app)
    # Added innermost first. Request flows: RequestId -> AccessLog -> UnhandledError -> routes,
    # so the request ID exists for both the access log and any 500 response.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(users_router, prefix=API_PREFIX)
    app.include_router(groups_router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)
    app.include_router(audit_router, prefix=API_PREFIX)
    app.include_router(questions_router, prefix=API_PREFIX)
    app.include_router(languages_router, prefix=API_PREFIX)
    app.include_router(images_router, prefix=API_PREFIX)
    app.include_router(exams_router, prefix=API_PREFIX)
    app.include_router(admin_exams_router, prefix=API_PREFIX)
    app.include_router(student_exams_router, prefix=API_PREFIX)
    app.include_router(attempts_router, prefix=API_PREFIX)
    app.include_router(runs_router, prefix=API_PREFIX)
    app.include_router(submissions_router, prefix=API_PREFIX)
    # Refuse to start if any route forgot to declare who may call it (SECURITY § 3.1).
    assert_routes_declared(app)
    return app


app = create_app()
