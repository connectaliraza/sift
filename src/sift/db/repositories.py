"""SQLAlchemy implementation of the ``DocumentRepository`` port."""

import uuid

from psycopg import errors as pg_errors
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sift.db.models import DocumentRow
from sift.domain.errors import DuplicateIdempotencyKeyError
from sift.domain.models import ContentType, Document, DocumentStatus

IDEMPOTENCY_CONSTRAINT = "uq_documents_idempotency_key"


def to_domain(row: DocumentRow) -> Document:
    return Document(
        id=row.id,
        original_filename=row.original_filename,
        content_type=ContentType(row.content_type),
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        storage_key=row.storage_key,
        page_count=row.page_count,
        status=DocumentStatus(row.status),
        idempotency_key=row.idempotency_key,
        webhook_url=row.webhook_url,
        failure_reason=row.failure_reason,
        attempts=row.attempts,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_row(doc: Document) -> DocumentRow:
    return DocumentRow(
        id=doc.id,
        idempotency_key=doc.idempotency_key,
        original_filename=doc.original_filename,
        content_type=doc.content_type.value,
        size_bytes=doc.size_bytes,
        sha256=doc.sha256,
        storage_key=doc.storage_key,
        page_count=doc.page_count,
        status=doc.status.value,
        failure_reason=doc.failure_reason,
        attempts=doc.attempts,
        webhook_url=doc.webhook_url,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


class SqlDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, document_id: uuid.UUID) -> Document | None:
        row = await self._session.get(DocumentRow, document_id)
        return to_domain(row) if row else None

    async def get_by_idempotency_key(self, key: str) -> Document | None:
        row = await self._session.scalar(
            select(DocumentRow).where(DocumentRow.idempotency_key == key)
        )
        return to_domain(row) if row else None

    async def add(self, document: Document) -> None:
        self._session.add(_to_row(document))
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _is_idempotency_violation(exc):
                raise DuplicateIdempotencyKeyError(
                    "Idempotency key already used by a concurrent request."
                ) from exc
            raise


def _is_idempotency_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    return (
        isinstance(orig, pg_errors.UniqueViolation)
        and orig.diag.constraint_name == IDEMPOTENCY_CONSTRAINT
    )
