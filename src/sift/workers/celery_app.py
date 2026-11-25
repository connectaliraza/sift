"""Celery worker entrypoint.

    celery -A sift.workers.celery_app worker -Q ocr,llm,default

Signals wire in logging and the correlation ID, so every log line from a task
can be joined to the API request that created it.
"""

from typing import Any

import structlog
from celery.signals import task_postrun, task_prerun, worker_process_init, worker_process_shutdown

from sift.adapters.celery_queue import create_celery_app
from sift.core.config import get_settings
from sift.core.context import CELERY_CORRELATION_HEADER, bind_correlation_id, clear_context
from sift.core.logging import configure_logging
from sift.workers import resources

settings = get_settings()
configure_logging(settings.log_level, json=settings.log_json)

app = create_celery_app(settings, include=["sift.workers.tasks"])

log = structlog.get_logger(__name__)


@worker_process_init.connect
def _init_worker_process(**_: Any) -> None:
    # Create DB pools *after* fork: connections must never be shared across processes.
    resources.init(settings)


@worker_process_shutdown.connect
def _shutdown_worker_process(**_: Any) -> None:
    resources.close()


def _correlation_id_from(task: Any) -> str | None:
    request = task.request
    value = request.get(CELERY_CORRELATION_HEADER) or (request.headers or {}).get(
        CELERY_CORRELATION_HEADER
    )
    return value if isinstance(value, str) else None


@task_prerun.connect
def _bind_task_context(task_id: str, task: Any, args: tuple[Any, ...], **_: Any) -> None:
    clear_context()
    correlation_id = _correlation_id_from(task)
    if correlation_id:
        bind_correlation_id(correlation_id)
    structlog.contextvars.bind_contextvars(task_id=task_id, task_name=task.name)
    if args:
        structlog.contextvars.bind_contextvars(document_id=str(args[0]))


@task_postrun.connect
def _clear_task_context(**_: Any) -> None:
    clear_context()
