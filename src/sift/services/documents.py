"""Use case: read documents."""

import uuid

from sift.domain.errors import DocumentNotFoundError
from sift.domain.models import Document
from sift.ports import DocumentRepository


class DocumentQueryService:
    def __init__(self, *, repository: DocumentRepository) -> None:
        self._repo = repository

    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self._repo.get(document_id)
        if document is None:
            raise DocumentNotFoundError(f"Document {document_id} was not found.")
        return document
