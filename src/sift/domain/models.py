"""Domain entities and value objects. No framework imports allowed here."""

import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DocumentStatus(StrEnum):
    RECEIVED = "received"
    OCR_DONE = "ocr_done"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"


class ContentType(StrEnum):
    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"

    @property
    def extension(self) -> str:
        return {ContentType.PDF: "pdf", ContentType.PNG: "png", ContentType.JPEG: "jpg"}[self]


def uuid7() -> uuid.UUID:
    """Time-ordered UUID (RFC 9562, version 7).

    Python 3.14 ships ``uuid.uuid7``; until we move to it, this keeps primary keys
    roughly sorted by creation time (good B-tree locality, natural cursor pagination).
    """
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= (rand >> 68) << 64  # rand_a: 12 bits
    value |= 0b10 << 62  # variant
    value |= rand & ((1 << 62) - 1)  # rand_b: 62 bits
    return uuid.UUID(int=value)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Document:
    id: uuid.UUID
    original_filename: str
    content_type: ContentType
    size_bytes: int
    sha256: str
    storage_key: str
    page_count: int
    status: DocumentStatus
    idempotency_key: str | None = None
    webhook_url: str | None = None
    failure_reason: str | None = None
    attempts: int = 0
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @staticmethod
    def storage_key_for(document_id: uuid.UUID, content_type: ContentType) -> str:
        return f"documents/{document_id}/original.{content_type.extension}"
