"""File-type detection from content, never from the client-supplied name or header."""

from sift.domain.models import ContentType

_SIGNATURES: tuple[tuple[bytes, ContentType], ...] = (
    (b"%PDF-", ContentType.PDF),
    (b"\x89PNG\r\n\x1a\n", ContentType.PNG),
    (b"\xff\xd8\xff", ContentType.JPEG),
)


def detect_content_type(data: bytes) -> ContentType | None:
    head = data[:16]
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    return None


def safe_filename(name: str | None, max_length: int = 255) -> str:
    """Keep only the base name, strip control characters, cap the length.

    The name is stored for display only; it never becomes part of a storage path.
    """
    if not name:
        return "upload"
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    return (cleaned or "upload")[:max_length]
