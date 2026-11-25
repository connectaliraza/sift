"""Celery tasks: thin wrappers around services (TRD §8.2).

Week 1 ships the entry task only, proving the API -> broker -> worker -> DB path
end to end with one correlation ID. Week 2 turns it into the chain
``ocr_document | extract_invoice | finalize_document``.
"""

import uuid

import structlog

from sift.adapters.celery_queue import PROCESS_DOCUMENT_TASK
from sift.db.models import DocumentRow
from sift.workers import resources
from sift.workers.celery_app import app

log = structlog.get_logger(__name__)


@app.task(name=PROCESS_DOCUMENT_TASK)
def process_document(document_id: str) -> None:
    doc_id = uuid.UUID(document_id)
    with resources.session_scope() as session:
        row = session.get(DocumentRow, doc_id)
        if row is None:
            # Not an error worth retrying: the row is the source of truth.
            log.warning("document.not_found")
            return
        status = row.status

    log.info("pipeline.started", status=status, note="OCR/extraction arrive in week 2")
