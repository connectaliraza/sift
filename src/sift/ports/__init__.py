"""Ports: the interfaces services depend on. Adapters implement them.

Swapping free tools for paid ones (RustFS -> AWS S3, Tesseract -> Textract,
Ollama -> a hosted LLM) means writing a new adapter, never touching services.
"""

import uuid
from typing import Protocol

from sift.domain.models import ContentType, Document


class DocumentRepository(Protocol):
    async def get(self, document_id: uuid.UUID) -> Document | None: ...

    async def get_by_idempotency_key(self, key: str) -> Document | None: ...

    async def add(self, document: Document) -> None:
        """Persist a new document.

        Raises ``DuplicateIdempotencyKeyError`` if another request inserted the
        same idempotency key first.
        """
        ...


class ObjectStorage(Protocol):
    """Blocking interface; async callers run it in a thread."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def check(self) -> None:
        """Raise if storage is unreachable or the bucket is missing."""
        ...


class DocumentInspector(Protocol):
    def page_count(self, data: bytes, content_type: ContentType) -> int:
        """Raise ``UnreadableDocumentError`` for corrupt or encrypted files."""
        ...


class TaskQueue(Protocol):
    def enqueue_document(self, document_id: uuid.UUID, correlation_id: str | None) -> None: ...
