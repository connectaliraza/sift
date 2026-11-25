import uuid

import pytest

from sift.domain.files import detect_content_type, safe_filename
from sift.domain.models import ContentType, Document, uuid7
from tests.factories import make_pdf, make_png


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (make_pdf(), ContentType.PDF),
        (make_png(), ContentType.PNG),
        (b"\xff\xd8\xff\xe0rest-of-jpeg", ContentType.JPEG),
        (b"PK\x03\x04zip-file", None),
        (b"<html>", None),
        (b"", None),
    ],
)
def test_detect_content_type_uses_magic_bytes(data: bytes, expected: ContentType | None) -> None:
    assert detect_content_type(data) is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("invoice.pdf", "invoice.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\ali\\inv.pdf", "inv.pdf"),
        ("bad\x00name\n.pdf", "badname.pdf"),
        ("", "upload"),
        (None, "upload"),
        ("a" * 400, "a" * 255),
    ],
)
def test_safe_filename(name: str | None, expected: str) -> None:
    assert safe_filename(name) == expected


def test_uuid7_has_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_is_time_ordered() -> None:
    ids = [uuid7() for _ in range(200)]
    # Same-millisecond IDs are random within the ms, so compare the timestamp prefix.
    prefixes = [i.int >> 80 for i in ids]
    assert prefixes == sorted(prefixes)


def test_storage_key_never_uses_client_filename() -> None:
    doc_id = uuid7()
    assert Document.storage_key_for(doc_id, ContentType.PDF) == f"documents/{doc_id}/original.pdf"
