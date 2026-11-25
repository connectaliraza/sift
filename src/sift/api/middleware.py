"""Pure ASGI middleware (no BaseHTTPMiddleware: it breaks contextvars and streaming)."""

import time
from http import HTTPStatus

import structlog
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sift.api.errors import problem
from sift.core.context import (
    CORRELATION_HEADER,
    bind_correlation_id,
    clear_context,
    sanitize_correlation_id,
)

log = structlog.get_logger("sift.access")

_HEADER_BYTES = CORRELATION_HEADER.lower().encode()


class CorrelationIdMiddleware:
    """Binds a correlation ID for the request, echoes it back, and logs access."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = next(
            (v.decode("latin-1") for k, v in scope["headers"] if k == _HEADER_BYTES), None
        )
        correlation_id = sanitize_correlation_id(incoming)
        clear_context()
        bind_correlation_id(correlation_id)

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((_HEADER_BYTES, correlation_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if scope["path"] not in ("/health", "/ready"):
                log.info(
                    "http.request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status_code,
                    duration_ms=round((time.perf_counter() - start) * 1000, 1),
                )
            clear_context()


class BodyTooLargeError(HTTPException):
    def __init__(self, limit: int) -> None:
        super().__init__(status_code=413, detail=f"Request body exceeds the {limit} byte limit.")


class BodySizeLimitMiddleware:
    """Cap request bodies *before* the app parses them.

    Rejects on ``Content-Length`` immediately and also counts streamed bytes,
    which covers chunked uploads that send no ``Content-Length``. Subclassing
    ``HTTPException`` lets FastAPI's body parser re-raise it untouched, so the
    client gets a proper 413 problem response.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for key, value in scope["headers"]:
            if key == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                response = problem(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Request body exceeds the {self.max_bytes} byte limit.",
                    code="file_too_large",
                )
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLargeError(self.max_bytes)
            return message

        await self.app(scope, limited_receive, send)
