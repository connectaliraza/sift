"""End-to-end through the real adapters: HTTP -> service -> Postgres + S3 + Redis."""

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import API_KEY, make_pdf
from tests.integration.conftest import BUCKET

pytestmark = pytest.mark.integration

AUTH = {"X-API-Key": API_KEY}


def _upload(data: bytes) -> dict[str, Any]:
    return {"files": {"file": ("invoice.pdf", data, "application/pdf")}}


async def test_upload_persists_row_object_and_task(
    client: httpx.AsyncClient, engine: AsyncEngine, redis: Redis, s3_client: Any
) -> None:
    pdf = make_pdf(pages=2)
    response = await client.post(
        "/v1/documents", headers={**AUTH, "X-Request-ID": "trace-42"}, **_upload(pdf)
    )
    assert response.status_code == 202, response.text
    doc_id = response.json()["id"]

    # Row
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, page_count, storage_key FROM documents WHERE id = :id"),
                {"id": doc_id},
            )
        ).one()
    assert row.status == "received"
    assert row.page_count == 2

    # Object
    stored = s3_client.get_object(Bucket=BUCKET, Key=row.storage_key)["Body"].read()
    assert stored == pdf

    # Celery message on the "default" queue, carrying the correlation ID
    raw = await redis.lpop("default")
    assert isinstance(raw, bytes)
    message = json.loads(raw)
    assert message["headers"]["task"] == "sift.process_document"
    assert message["headers"]["sift_correlation_id"] == "trace-42"
    args, _, _ = json.loads(base64.b64decode(message["body"]))
    assert args == [doc_id]


async def test_get_reads_from_database(client: httpx.AsyncClient) -> None:
    created = await client.post("/v1/documents", headers=AUTH, **_upload(make_pdf()))
    doc_id = created.json()["id"]

    response = await client.get(f"/v1/documents/{doc_id}", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "received"


async def test_concurrent_requests_with_same_key_create_one_document(
    client: httpx.AsyncClient, engine: AsyncEngine, s3_client: Any
) -> None:
    """Exercises the unique-constraint race path against real Postgres."""
    pdf = make_pdf()
    headers = {**AUTH, "Idempotency-Key": "concurrent-key"}

    responses = await asyncio.gather(
        *(client.post("/v1/documents", headers=headers, **_upload(pdf)) for _ in range(8))
    )

    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["id"] for r in responses}) == 1
    async with engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM documents"))
    assert count == 1
    # Losers removed their orphaned uploads.
    objects = s3_client.list_objects_v2(Bucket=BUCKET, Prefix="documents/").get("Contents", [])
    assert len([o for o in objects if responses[0].json()["id"] in o["Key"]]) == 1


async def test_ready_reports_all_dependencies(client: httpx.AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok", "storage": "ok"},
    }


async def test_ready_is_503_when_storage_bucket_missing(
    client: httpx.AsyncClient, s3_client: Any
) -> None:
    for obj in s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", []):
        s3_client.delete_object(Bucket=BUCKET, Key=obj["Key"])
    s3_client.delete_bucket(Bucket=BUCKET)

    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["storage"] == "unavailable"
