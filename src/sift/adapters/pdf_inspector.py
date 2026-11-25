"""Page counting with pypdf. Images are always one page."""

import io

from pypdf import PdfReader

from sift.domain.errors import UnreadableDocumentError
from sift.domain.models import ContentType


class PypdfInspector:
    def page_count(self, data: bytes, content_type: ContentType) -> int:
        if content_type is not ContentType.PDF:
            return 1
        try:
            reader = PdfReader(io.BytesIO(data))
            encrypted = reader.is_encrypted
            count = 0 if encrypted else len(reader.pages)
        except Exception as exc:
            # pypdf raises a variety of exception types on malformed input.
            raise UnreadableDocumentError("The PDF could not be read.") from exc
        if encrypted:
            raise UnreadableDocumentError("Encrypted PDFs are not supported.")
        if count == 0:
            raise UnreadableDocumentError("The PDF has no pages.")
        return count
