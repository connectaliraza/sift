"""Response DTOs. Kept separate from domain entities so the API contract can
evolve independently of internal models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from sift.domain.models import ContentType, Document, DocumentStatus


class DocumentAccepted(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    status: DocumentStatus
    created_at: datetime

    @classmethod
    def from_domain(cls, doc: Document) -> "DocumentAccepted":
        return cls(id=doc.id, status=doc.status, created_at=doc.created_at)


class DocumentOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    status: DocumentStatus
    original_filename: str
    content_type: ContentType
    size_bytes: int
    page_count: int
    sha256: str
    failure_reason: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, doc: Document) -> "DocumentOut":
        return cls(
            id=doc.id,
            status=doc.status,
            original_filename=doc.original_filename,
            content_type=doc.content_type,
            size_bytes=doc.size_bytes,
            page_count=doc.page_count,
            sha256=doc.sha256,
            failure_reason=doc.failure_reason,
            attempts=doc.attempts,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )


class HealthOut(BaseModel):
    status: str


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, str]
