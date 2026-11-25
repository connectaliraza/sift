"""In-memory implementations of the ports, for fast unit tests."""

import uuid
from dataclasses import dataclass, field

from sift.domain.errors import DuplicateIdempotencyKeyError
from sift.domain.models import ContentType, Document


@dataclass
class FakeRepository:
    documents: dict[uuid.UUID, Document] = field(default_factory=dict)
    fail_add_with: Exception | None = None
    # Simulates a concurrent request inserting the same key just before us.
    race_winner: Document | None = None

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return self.documents.get(document_id)

    async def get_by_idempotency_key(self, key: str) -> Document | None:
        return next((d for d in self.documents.values() if d.idempotency_key == key), None)

    async def add(self, document: Document) -> None:
        if self.race_winner is not None:
            self.documents[self.race_winner.id] = self.race_winner
            self.race_winner = None
            raise DuplicateIdempotencyKeyError("race lost")
        if self.fail_add_with is not None:
            raise self.fail_add_with
        self.documents[document.id] = document


@dataclass
class FakeStorage:
    objects: dict[str, bytes] = field(default_factory=dict)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def check(self) -> None:
        return None


@dataclass
class FakeInspector:
    pages: int = 1

    def page_count(self, data: bytes, content_type: ContentType) -> int:
        return self.pages


@dataclass
class FakeQueue:
    enqueued: list[tuple[uuid.UUID, str | None]] = field(default_factory=list)
    fail: bool = False

    def enqueue_document(self, document_id: uuid.UUID, correlation_id: str | None) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.enqueued.append((document_id, correlation_id))
