import pytest

from sift.adapters.pdf_inspector import PypdfInspector
from sift.domain.errors import UnreadableDocumentError
from sift.domain.models import ContentType
from tests.factories import make_encrypted_pdf, make_pdf, make_png

inspector = PypdfInspector()


def test_counts_pdf_pages() -> None:
    assert inspector.page_count(make_pdf(pages=4), ContentType.PDF) == 4


def test_images_are_one_page() -> None:
    assert inspector.page_count(make_png(), ContentType.PNG) == 1


def test_corrupt_pdf_is_unreadable() -> None:
    with pytest.raises(UnreadableDocumentError):
        inspector.page_count(b"%PDF-1.7\n garbage that is not a pdf", ContentType.PDF)


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(UnreadableDocumentError, match="Encrypted"):
        inspector.page_count(make_encrypted_pdf(), ContentType.PDF)
