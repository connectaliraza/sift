"""Document endpoints (v1)."""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from sift.api.deps import StateDep, get_ingest_service, get_query_service, require_api_key
from sift.api.schemas import DocumentAccepted, DocumentOut
from sift.core.context import get_correlation_id
from sift.services.documents import DocumentQueryService
from sift.services.ingest import IngestService, UploadCommand

router = APIRouter(
    prefix="/v1/documents", tags=["documents"], dependencies=[Depends(require_api_key)]
)

_URL = TypeAdapter(AnyHttpUrl)


@router.post(
    "",
    status_code=HTTPStatus.ACCEPTED,
    response_model=DocumentAccepted,
    summary="Upload an invoice for processing",
    responses={
        HTTPStatus.CONFLICT.value: {"description": "Idempotency-Key reused with a different file"},
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE.value: {"description": "File too large"},
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE.value: {"description": "Not a PDF, PNG or JPEG"},
    },
)
async def upload_document(
    state: StateDep,
    service: Annotated[IngestService, Depends(get_ingest_service)],
    file: Annotated[UploadFile, File(description="PDF, PNG or JPEG invoice")],
    webhook_url: Annotated[str | None, Form()] = None,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ] = None,
) -> JSONResponse:
    if webhook_url:
        try:
            webhook_url = str(_URL.validate_python(webhook_url))
        except ValidationError as exc:
            raise HTTPException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                detail="webhook_url must be an http(s) URL.",
            ) from exc

    # Read at most one byte over the limit; the service turns that into a 413.
    data = await file.read(state.settings.max_upload_bytes + 1)

    result = await service.ingest(
        UploadCommand(
            filename=file.filename,
            data=data,
            idempotency_key=idempotency_key,
            webhook_url=webhook_url,
        ),
        correlation_id=get_correlation_id(),
    )
    body = DocumentAccepted.from_domain(result.document)
    headers = {"Location": f"/v1/documents/{result.document.id}"}
    if result.replayed:
        headers["Idempotent-Replayed"] = "true"
    return JSONResponse(
        body.model_dump(mode="json"), status_code=HTTPStatus.ACCEPTED, headers=headers
    )


@router.get("/{document_id}", response_model=DocumentOut, summary="Get a document's status")
async def get_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentQueryService, Depends(get_query_service)],
) -> DocumentOut:
    return DocumentOut.from_domain(await service.get(document_id))
