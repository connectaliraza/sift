"""Composition root for the API: wires adapters into services per request."""

import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sift.core.config import Settings
from sift.db.repositories import SqlDocumentRepository
from sift.ports import DocumentInspector, ObjectStorage, TaskQueue
from sift.services.documents import DocumentQueryService
from sift.services.ingest import IngestLimits, IngestService


@dataclass(slots=True)
class AppState:
    """Long-lived resources created once in the lifespan handler."""

    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: ObjectStorage
    inspector: DocumentInspector
    queue: TaskQueue


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.sift
    return state


StateDep = Annotated[AppState, Depends(get_state)]


async def get_session(state: StateDep) -> AsyncIterator[AsyncSession]:
    async with state.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    state: StateDep, api_key: Annotated[str | None, Security(_api_key_header)]
) -> None:
    expected = state.settings.api_key.get_secret_value().encode()
    if not api_key or not hmac.compare_digest(api_key.encode(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
            headers={"WWW-Authenticate": "APIKey"},
        )


def get_ingest_service(state: StateDep, session: SessionDep) -> IngestService:
    return IngestService(
        repository=SqlDocumentRepository(session),
        storage=state.storage,
        inspector=state.inspector,
        queue=state.queue,
        limits=IngestLimits(
            max_bytes=state.settings.max_upload_bytes, max_pages=state.settings.max_pages
        ),
    )


def get_query_service(session: SessionDep) -> DocumentQueryService:
    return DocumentQueryService(repository=SqlDocumentRepository(session))
