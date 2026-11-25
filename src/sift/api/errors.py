"""RFC 9457 Problem Details for every error response."""

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sift.core.context import get_correlation_id
from sift.domain import errors as d

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"

_STATUS_BY_ERROR: dict[type[d.DomainError], HTTPStatus] = {
    d.EmptyFileError: HTTPStatus.UNPROCESSABLE_ENTITY,
    d.FileTooLargeError: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    d.UnsupportedFileTypeError: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    d.TooManyPagesError: HTTPStatus.UNPROCESSABLE_ENTITY,
    d.UnreadableDocumentError: HTTPStatus.UNPROCESSABLE_ENTITY,
    d.DocumentNotFoundError: HTTPStatus.NOT_FOUND,
    d.IdempotencyKeyConflictError: HTTPStatus.CONFLICT,
    d.TransientError: HTTPStatus.SERVICE_UNAVAILABLE,
}


def problem(
    status: HTTPStatus,
    *,
    detail: str | None = None,
    code: str | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://github.com/connectaliraza/sift/blob/main/docs/errors.md#{code}"
        if code
        else "about:blank",
        "title": status.phrase,
        "status": status.value,
    }
    if detail:
        body["detail"] = detail
    if code:
        body["code"] = code
    if correlation_id := get_correlation_id():
        body["correlation_id"] = correlation_id
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status.value, media_type=PROBLEM_JSON, headers=headers)


def _status_for(exc: d.DomainError) -> HTTPStatus:
    for error_type in type(exc).__mro__:
        if error_type in _STATUS_BY_ERROR:
            return _STATUS_BY_ERROR[error_type]
    return HTTPStatus.INTERNAL_SERVER_ERROR


async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, d.DomainError)  # noqa: S101 - registered for DomainError only
    status = _status_for(exc)
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        log.error("request.domain_error", code=exc.code, exc_info=exc)
    return problem(status, detail=exc.detail, code=exc.code)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    return problem(
        HTTPStatus(exc.status_code),
        detail=str(exc.detail) if exc.detail else None,
        headers=getattr(exc, "headers", None),
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return problem(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        detail="Request validation failed.",
        code="validation_error",
        extra={"errors": errors},
    )


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.error("request.unhandled_error", exc_info=exc)
    return problem(HTTPStatus.INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(d.DomainError, _domain_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
