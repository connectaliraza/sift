"""Correlation-ID handling shared by the API and the workers.

The ID is created (or accepted from ``X-Request-ID``) at the API edge, bound to
structlog's contextvars, sent to Celery as a message header, and re-bound in the
worker before the task runs. One ID follows a document end to end.
"""

import re
import uuid

import structlog

CORRELATION_HEADER = "X-Request-ID"
CELERY_CORRELATION_HEADER = "sift_correlation_id"

_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def sanitize_correlation_id(value: str | None) -> str:
    """Accept a client-supplied ID only if it is safe to log; otherwise make a new one."""
    if value and _VALID_ID.fullmatch(value):
        return value
    return new_correlation_id()


def bind_correlation_id(correlation_id: str) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def get_correlation_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return value if isinstance(value, str) else None


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
