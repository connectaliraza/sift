"""Celery app factory and the ``TaskQueue`` adapter.

The API only *publishes* tasks by name (``send_task``), so it never imports the
worker code. Settings mirror TRD §8.2; each one is there for a failure mode.
"""

import uuid

from celery import Celery
from kombu.entity import Queue

from sift.core.config import Settings
from sift.core.context import CELERY_CORRELATION_HEADER

PROCESS_DOCUMENT_TASK = "sift.process_document"

QUEUE_OCR = "ocr"
QUEUE_LLM = "llm"
QUEUE_DEFAULT = "default"

# Longest task (LLM extraction) is capped at 240 s; visibility must exceed it,
# or Redis re-delivers a task that is still running.
VISIBILITY_TIMEOUT_S = 3600


def create_celery_app(settings: Settings, *, include: list[str] | None = None) -> Celery:
    app = Celery("sift", broker=settings.redis_url, include=include or [])
    app.conf.update(
        # Reliability: re-deliver if a worker dies mid-task. Tasks must be idempotent.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_S},
        broker_connection_retry_on_startup=True,
        # State lives in Postgres; the Celery result backend is not used.
        task_ignore_result=True,
        # Safety
        task_serializer="json",
        accept_content=["json"],
        # Default limits; individual tasks override.
        task_time_limit=300,
        task_soft_time_limit=240,
        task_track_started=True,
        # Routing (TRD §2.2): separate pools for CPU-bound OCR and I/O-bound LLM work.
        task_default_queue=QUEUE_DEFAULT,
        task_queues=(Queue(QUEUE_OCR), Queue(QUEUE_LLM), Queue(QUEUE_DEFAULT)),
        task_routes={
            "sift.ocr_*": {"queue": QUEUE_OCR},
            "sift.extract_*": {"queue": QUEUE_LLM},
            "sift.*": {"queue": QUEUE_DEFAULT},
        },
        worker_hijack_root_logger=False,
        worker_redirect_stdouts=False,
        worker_send_task_events=True,
        task_send_sent_event=True,
    )
    return app


class CeleryTaskQueue:
    def __init__(self, app: Celery) -> None:
        self._app = app

    def enqueue_document(self, document_id: uuid.UUID, correlation_id: str | None) -> None:
        self._app.send_task(
            PROCESS_DOCUMENT_TASK,
            args=[str(document_id)],
            headers={CELERY_CORRELATION_HEADER: correlation_id} if correlation_id else None,
        )
