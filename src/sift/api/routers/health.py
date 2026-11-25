"""Liveness and readiness probes.

``/health``: the process is up (never touches dependencies, so a slow DB
doesn't get the container killed). ``/ready``: dependencies are reachable,
so traffic can be routed here.
"""

import asyncio
from http import HTTPStatus

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from sift.api.deps import StateDep
from sift.api.schemas import HealthOut, ReadyOut

router = APIRouter(tags=["ops"])
log = structlog.get_logger(__name__)

_CHECK_TIMEOUT_S = 2.0


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok")


@router.get(
    "/ready",
    response_model=ReadyOut,
    responses={HTTPStatus.SERVICE_UNAVAILABLE.value: {"model": ReadyOut}},
)
async def ready(state: StateDep) -> JSONResponse:
    async def database() -> None:
        async with state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis() -> None:
        await state.redis.ping()

    async def storage() -> None:
        await asyncio.to_thread(state.storage.check)

    checks = {"database": database, "redis": redis, "storage": storage}
    results = await asyncio.gather(
        *(asyncio.wait_for(fn(), _CHECK_TIMEOUT_S) for fn in checks.values()),
        return_exceptions=True,
    )

    report: dict[str, str] = {}
    for name, result in zip(checks, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("ready.check_failed", check=name, error=type(result).__name__)
            report[name] = "unavailable"
        else:
            report[name] = "ok"

    healthy = all(v == "ok" for v in report.values())
    body = ReadyOut(status="ok" if healthy else "degraded", checks=report)
    return JSONResponse(
        body.model_dump(),
        status_code=HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
    )
