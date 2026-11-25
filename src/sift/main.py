"""FastAPI application factory.

Run with: ``uvicorn sift.main:create_app --factory``
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from sift import __version__
from sift.adapters.celery_queue import CeleryTaskQueue, create_celery_app
from sift.adapters.pdf_inspector import PypdfInspector
from sift.adapters.s3_storage import S3ObjectStorage
from sift.api.deps import AppState
from sift.api.errors import register_error_handlers
from sift.api.middleware import BodySizeLimitMiddleware, CorrelationIdMiddleware
from sift.api.routers import documents, health
from sift.core.config import Settings, get_settings
from sift.core.logging import configure_logging
from sift.db.session import make_async_engine, make_async_sessionmaker

log = structlog.get_logger(__name__)

# Multipart framing allowed on top of the file-size limit.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def build_state(settings: Settings) -> AppState:
    engine = make_async_engine(settings.database_url)
    return AppState(
        settings=settings,
        engine=engine,
        sessionmaker=make_async_sessionmaker(engine),
        redis=Redis.from_url(settings.redis_url, socket_timeout=2),
        storage=S3ObjectStorage.from_settings(settings),
        inspector=PypdfInspector(),
        queue=CeleryTaskQueue(create_celery_app(settings)),
    )


def create_app(state: AppState | None = None) -> FastAPI:
    """Build the app. Tests pass a pre-built ``state`` with fakes or test containers."""
    settings = state.settings if state else get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app_state = state or build_state(settings)
        app.state.sift = app_state
        log.info("app.started", version=__version__, environment=settings.environment)
        try:
            yield
        finally:
            await app_state.redis.aclose()
            await app_state.engine.dispose()
            log.info("app.stopped")

    app = FastAPI(
        title="Sift",
        version=__version__,
        summary="Self-hosted invoice extraction with human review.",
        lifespan=lifespan,
    )
    # Middleware added last runs first: correlation ID wraps everything.
    app.add_middleware(
        BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    )
    app.add_middleware(CorrelationIdMiddleware)
    if state is not None:
        # Injected state is usable immediately (tests don't always run the lifespan).
        app.state.sift = state
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(documents.router)
    return app
