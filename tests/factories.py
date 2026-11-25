"""Test data builders."""

import io
import struct
import zlib

from pydantic import SecretStr
from pypdf import PdfWriter

from sift.core.config import Settings

API_KEY = "test-api-key"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "log_json": False,
        "log_level": "WARNING",
        "api_key": SecretStr(API_KEY),
        "webhook_signing_secret": SecretStr("test-webhook-secret"),
        "database_url": "postgresql+psycopg://unused/unused",
        "redis_url": "redis://localhost:6379/15",
        "max_upload_mb": 1,
        "max_pages": 3,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def make_pdf(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_png() -> bytes:
    """A valid 1x1 PNG, built by hand to avoid an imaging dependency."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\xff\xff")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )
