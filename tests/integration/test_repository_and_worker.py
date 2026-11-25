"""Repository edge cases and the worker task, against real Postgres."""

import importlib
from dataclasses import replace

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from sift.core.config import Settings, get_settings
from sift.db.repositories import SqlDocumentRepository
from sift.db.session import make_async_sessionmaker
from sift.domain.errors import DuplicateIdempotencyKeyError
from sift.domain.models import ContentType, Document, DocumentStatus, uuid7

pytestmark = pytest.mark.integration


def _document(key: str | None = None) -> Document:
    doc_id = uuid7()
    return Document(
        id=doc_id,
        original_filename="inv.pdf",
        content_type=ContentType.PDF,
        size_bytes=100,
        sha256="0" * 64,
        storage_key=Document.storage_key_for(doc_id, ContentType.PDF),
        page_count=1,
        status=DocumentStatus.RECEIVED,
        idempotency_key=key,
    )


async def test_duplicate_idempotency_key_maps_to_domain_error(engine: AsyncEngine) -> None:
    sessions = make_async_sessionmaker(engine)
    async with sessions() as s:
        await SqlDocumentRepository(s).add(_document("dup"))
    async with sessions() as s:
        with pytest.raises(DuplicateIdempotencyKeyError):
            await SqlDocumentRepository(s).add(_document("dup"))


async def test_other_integrity_errors_are_not_masked(engine: AsyncEngine) -> None:
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    sessions = make_async_sessionmaker(engine)
    first = _document()
    async with sessions() as s:
        await SqlDocumentRepository(s).add(first)
    async with sessions() as s:
        # Same primary key: a unique violation that is NOT the idempotency constraint.
        with pytest.raises(IntegrityError):
            await SqlDocumentRepository(s).add(replace(first, idempotency_key="other"))


async def test_round_trip_preserves_fields(engine: AsyncEngine) -> None:
    sessions = make_async_sessionmaker(engine)
    doc = _document("rt")
    async with sessions() as s:
        await SqlDocumentRepository(s).add(doc)
    async with sessions() as s:
        loaded = await SqlDocumentRepository(s).get(doc.id)
    assert loaded is not None
    assert (loaded.id, loaded.content_type, loaded.status, loaded.idempotency_key) == (
        doc.id,
        doc.content_type,
        doc.status,
        "rt",
    )


async def test_worker_task_reads_document_and_binds_context(
    engine: AsyncEngine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Celery app reads settings at import time, like it does in production.
    for name, value in {
        "API_KEY": "x",
        "WEBHOOK_SIGNING_SECRET": "x",
        "DATABASE_URL": settings.database_url,
        "REDIS_URL": settings.redis_url,
        "LOG_JSON": "false",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    resources = importlib.import_module("sift.workers.resources")
    tasks = importlib.import_module("sift.workers.tasks")
    resources.init(get_settings())

    doc = _document()
    async with make_async_sessionmaker(engine)() as s:
        await SqlDocumentRepository(s).add(doc)

    with structlog.testing.capture_logs() as logs:
        tasks.process_document.apply(args=[str(doc.id)], headers={"sift_correlation_id": "c-9"})
        tasks.process_document.apply(args=[str(uuid7())])

    events = {entry["event"]: entry for entry in logs}
    assert events["pipeline.started"]["status"] == "received"
    assert "document.not_found" in events
    resources.close()
    get_settings.cache_clear()
