"""Use case: accept an uploaded file and start processing it.

Order of operations (see TRD §8.1):
  1. validate size and type (cheap checks first)
  2. idempotency lookup
  3. inspect page count
  4. store the file, then insert the DB row
  5. enqueue AFTER the row is committed

If step 5 fails the document stays ``received``; the stuck-job sweeper
(week 3) re-enqueues it. Postgres is the source of truth, not the broker.
"""

import asyncio
import uuid
from dataclasses import dataclass

import structlog

from sift.domain.errors import (
    DuplicateIdempotencyKeyError,
    EmptyFileError,
    FileTooLargeError,
    IdempotencyKeyConflictError,
    TooManyPagesError,
    UnsupportedFileTypeError,
)
from sift.domain.files import detect_content_type, safe_filename
from sift.domain.models import Document, DocumentStatus, sha256_hex, uuid7
from sift.ports import DocumentInspector, DocumentRepository, ObjectStorage, TaskQueue

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestLimits:
    max_bytes: int
    max_pages: int


@dataclass(frozen=True, slots=True)
class UploadCommand:
    filename: str | None
    data: bytes
    idempotency_key: str | None = None
    webhook_url: str | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    document: Document
    replayed: bool  # True when an earlier request with the same idempotency key is returned


class IngestService:
    def __init__(
        self,
        *,
        repository: DocumentRepository,
        storage: ObjectStorage,
        inspector: DocumentInspector,
        queue: TaskQueue,
        limits: IngestLimits,
    ) -> None:
        self._repo = repository
        self._storage = storage
        self._inspector = inspector
        self._queue = queue
        self._limits = limits

    async def ingest(self, cmd: UploadCommand, *, correlation_id: str | None) -> IngestResult:
        data = cmd.data
        if not data:
            raise EmptyFileError("The uploaded file is empty.")
        if len(data) > self._limits.max_bytes:
            raise FileTooLargeError(f"File exceeds the {self._limits.max_bytes} byte limit.")

        content_type = detect_content_type(data)
        if content_type is None:
            raise UnsupportedFileTypeError("Only PDF, PNG and JPEG files are supported.")

        digest = sha256_hex(data)

        if cmd.idempotency_key:
            existing = await self._repo.get_by_idempotency_key(cmd.idempotency_key)
            if existing is not None:
                return self._replay(existing, digest)

        pages = await asyncio.to_thread(self._inspector.page_count, data, content_type)
        if pages > self._limits.max_pages:
            raise TooManyPagesError(
                f"Document has {pages} pages; the limit is {self._limits.max_pages}."
            )

        document_id = uuid7()
        document = Document(
            id=document_id,
            original_filename=safe_filename(cmd.filename),
            content_type=content_type,
            size_bytes=len(data),
            sha256=digest,
            storage_key=Document.storage_key_for(document_id, content_type),
            page_count=pages,
            status=DocumentStatus.RECEIVED,
            idempotency_key=cmd.idempotency_key,
            webhook_url=cmd.webhook_url,
        )
        structlog.contextvars.bind_contextvars(document_id=str(document_id))

        # Store the file first: a DB row must never point at a missing object.
        await asyncio.to_thread(self._storage.put, document.storage_key, data, content_type.value)
        try:
            await self._repo.add(document)
        except DuplicateIdempotencyKeyError:
            # A concurrent request with the same key won the race.
            await self._delete_orphan(document.storage_key)
            key = cmd.idempotency_key
            winner = await self._repo.get_by_idempotency_key(key) if key else None
            if winner is None:  # pragma: no cover - only raised when a key exists
                raise
            return self._replay(winner, digest)
        except Exception:
            await self._delete_orphan(document.storage_key)
            raise

        await self._enqueue(document.id, correlation_id)
        log.info("document.received", pages=pages, size_bytes=len(data))
        return IngestResult(document=document, replayed=False)

    def _replay(self, existing: Document, digest: str) -> IngestResult:
        if existing.sha256 != digest:
            raise IdempotencyKeyConflictError(
                "This Idempotency-Key was already used with a different file."
            )
        log.info("document.idempotent_replay", document_id=str(existing.id))
        return IngestResult(document=existing, replayed=True)

    async def _enqueue(self, document_id: uuid.UUID, correlation_id: str | None) -> None:
        try:
            await asyncio.to_thread(self._queue.enqueue_document, document_id, correlation_id)
        except Exception:
            # Accepted on purpose: the row is committed, so the sweeper recovers it.
            log.warning("document.enqueue_failed", exc_info=True)

    async def _delete_orphan(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._storage.delete, key)
        except Exception:
            log.warning("storage.orphan_cleanup_failed", storage_key=key, exc_info=True)
