"""Integration fixtures: real Postgres + Redis, S3 via moto's server.

By default Postgres and Redis come from testcontainers (needs Docker).
Set ``INTEGRATION_DATABASE_URL`` / ``INTEGRATION_REDIS_URL`` to use running
instances instead (e.g. ``docker compose up postgres redis``).
"""

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import boto3
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from moto.server import ThreadedMotoServer
from redis.asyncio import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from sift.adapters.celery_queue import CeleryTaskQueue, create_celery_app
from sift.adapters.pdf_inspector import PypdfInspector
from sift.adapters.s3_storage import S3ObjectStorage
from sift.api.deps import AppState
from sift.core.config import Settings
from sift.db.session import make_async_engine, make_async_sessionmaker
from sift.main import create_app
from tests.factories import make_settings

pytestmark = pytest.mark.integration

BUCKET = "sift-test"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if url := os.environ.get("INTEGRATION_DATABASE_URL"):
        yield url
        return
    with PostgresContainer("postgres:17-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    if url := os.environ.get("INTEGRATION_REDIS_URL"):
        yield url
        return
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def s3_endpoint() -> Iterator[str]:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Runs the real Alembic migrations: the schema under test is the shipped one."""
    os.environ["DATABASE_URL"] = database_url
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()
    command.upgrade(Config("alembic.ini"), "head")
    return database_url


@pytest.fixture
def settings(migrated_database: str, redis_url: str, s3_endpoint: str) -> Settings:
    return make_settings(
        database_url=migrated_database,
        redis_url=redis_url,
        s3_endpoint_url=s3_endpoint,
        s3_bucket=BUCKET,
        s3_access_key="test",
        s3_secret_key="test",
    )


@pytest.fixture
def storage(settings: Settings) -> S3ObjectStorage:
    store = S3ObjectStorage.from_settings(settings)
    store.ensure_bucket()
    return store


@pytest.fixture
def s3_client(settings: Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = make_async_engine(settings.database_url)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE documents"))
    yield eng
    await eng.dispose()


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.redis_url)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine, redis: Redis, storage: S3ObjectStorage) -> FastAPI:
    state = AppState(
        settings=settings,
        engine=engine,
        sessionmaker=make_async_sessionmaker(engine),
        redis=redis,
        storage=storage,
        inspector=PypdfInspector(),
        queue=CeleryTaskQueue(create_celery_app(settings)),
    )
    return create_app(state)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
