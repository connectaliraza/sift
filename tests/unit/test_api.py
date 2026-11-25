"""HTTP-layer tests with fakes behind the ports (no database, no network)."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from sift.api.deps import AppState, get_ingest_service, get_query_service
from sift.main import create_app
from sift.services.documents import DocumentQueryService
from sift.services.ingest import IngestLimits, IngestService
from tests.factories import API_KEY, make_pdf, make_settings
from tests.fakes import FakeInspector, FakeQueue, FakeRepository, FakeStorage


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def app(repo: FakeRepository) -> FastAPI:
    settings = make_settings()
    state = AppState(
        settings=settings,
        engine=MagicMock(),
        sessionmaker=MagicMock(),
        redis=MagicMock(),
        storage=FakeStorage(),
        inspector=FakeInspector(),
        queue=FakeQueue(),
    )
    application = create_app(state)
    application.dependency_overrides[get_ingest_service] = lambda: IngestService(
        repository=repo,
        storage=state.storage,
        inspector=state.inspector,
        queue=state.queue,
        limits=IngestLimits(max_bytes=settings.max_upload_bytes, max_pages=settings.max_pages),
    )
    application.dependency_overrides[get_query_service] = lambda: DocumentQueryService(
        repository=repo
    )
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


AUTH = {"X-API-Key": API_KEY}


def _upload(data: bytes, name: str = "inv.pdf") -> dict[str, Any]:
    return {"files": {"file": (name, data, "application/pdf")}}


async def test_health_needs_no_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_correlation_id_is_echoed_or_generated(client: httpx.AsyncClient) -> None:
    echoed = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"

    unsafe = await client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert unsafe.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(unsafe.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
async def test_documents_require_api_key(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.post("/v1/documents", headers=headers, **_upload(make_pdf()))
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 401


async def test_upload_returns_202_with_location(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/documents", headers=AUTH, **_upload(make_pdf()))
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "received"
    assert response.headers["Location"] == f"/v1/documents/{body['id']}"
    assert "Idempotent-Replayed" not in response.headers


async def test_idempotent_replay_sets_header(client: httpx.AsyncClient) -> None:
    headers = {**AUTH, "Idempotency-Key": "k-1"}
    first = await client.post("/v1/documents", headers=headers, **_upload(make_pdf()))
    second = await client.post("/v1/documents", headers=headers, **_upload(make_pdf()))
    assert first.json()["id"] == second.json()["id"]
    assert second.headers["Idempotent-Replayed"] == "true"


async def test_idempotency_conflict_is_409_problem(client: httpx.AsyncClient) -> None:
    headers = {**AUTH, "Idempotency-Key": "k-2"}
    await client.post("/v1/documents", headers=headers, **_upload(make_pdf(1)))
    response = await client.post("/v1/documents", headers=headers, **_upload(make_pdf(2)))
    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_key_conflict"
    assert "correlation_id" in response.json()


async def test_unsupported_type_is_415(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/documents", headers=AUTH, **_upload(b"hello", "a.txt"))
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_file_type"


async def test_oversized_body_rejected_by_middleware(client: httpx.AsyncClient) -> None:
    big = b"%PDF-" + b"0" * (2 * 1024 * 1024)  # limit in tests is 1 MB
    response = await client.post("/v1/documents", headers=AUTH, **_upload(big))
    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"


async def test_invalid_webhook_url_is_422(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/documents",
        headers=AUTH,
        data={"webhook_url": "ftp://example.com/hook"},
        **_upload(make_pdf()),
    )
    assert response.status_code == 422


async def test_get_document_round_trip(client: httpx.AsyncClient) -> None:
    created = await client.post("/v1/documents", headers=AUTH, **_upload(make_pdf()))
    doc_id = created.json()["id"]

    response = await client.get(f"/v1/documents/{doc_id}", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["id"] == doc_id
    assert response.json()["page_count"] == 1


async def test_unknown_document_is_404_problem(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/documents/0193f1c2-0000-7000-8000-000000000000", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["code"] == "document_not_found"


async def test_malformed_id_is_422(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/documents/not-a-uuid", headers=AUTH)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
