from dataclasses import replace

import pytest

from sift.domain.errors import (
    EmptyFileError,
    FileTooLargeError,
    IdempotencyKeyConflictError,
    TooManyPagesError,
    UnsupportedFileTypeError,
)
from sift.domain.models import DocumentStatus, sha256_hex
from sift.services.ingest import IngestLimits, IngestService, UploadCommand
from tests.factories import make_pdf
from tests.fakes import FakeInspector, FakeQueue, FakeRepository, FakeStorage

PDF = make_pdf()


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def inspector() -> FakeInspector:
    return FakeInspector(pages=2)


@pytest.fixture
def service(
    repo: FakeRepository, storage: FakeStorage, queue: FakeQueue, inspector: FakeInspector
) -> IngestService:
    return IngestService(
        repository=repo,
        storage=storage,
        inspector=inspector,
        queue=queue,
        limits=IngestLimits(max_bytes=10_000, max_pages=3),
    )


async def test_happy_path_stores_persists_and_enqueues(
    service: IngestService, repo: FakeRepository, storage: FakeStorage, queue: FakeQueue
) -> None:
    result = await service.ingest(
        UploadCommand(filename="inv.pdf", data=PDF), correlation_id="cid-1"
    )

    doc = result.document
    assert not result.replayed
    assert doc.status is DocumentStatus.RECEIVED
    assert doc.page_count == 2
    assert doc.sha256 == sha256_hex(PDF)
    assert repo.documents[doc.id] == doc
    assert storage.objects[doc.storage_key] == PDF
    assert queue.enqueued == [(doc.id, "cid-1")]


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"", EmptyFileError),
        (b"%PDF-" + b"x" * 10_001, FileTooLargeError),
        (b"MZ\x90\x00 an exe", UnsupportedFileTypeError),
    ],
)
async def test_rejects_invalid_input_before_side_effects(
    service: IngestService,
    storage: FakeStorage,
    queue: FakeQueue,
    data: bytes,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await service.ingest(UploadCommand(filename="x", data=data), correlation_id=None)
    assert storage.objects == {}
    assert queue.enqueued == []


async def test_rejects_too_many_pages(service: IngestService, inspector: FakeInspector) -> None:
    inspector.pages = 4
    with pytest.raises(TooManyPagesError):
        await service.ingest(UploadCommand(filename="x", data=PDF), correlation_id=None)


async def test_same_key_same_file_replays_without_side_effects(
    service: IngestService, storage: FakeStorage, queue: FakeQueue
) -> None:
    cmd = UploadCommand(filename="inv.pdf", data=PDF, idempotency_key="key-1")
    first = await service.ingest(cmd, correlation_id=None)
    second = await service.ingest(cmd, correlation_id=None)

    assert second.replayed
    assert second.document.id == first.document.id
    assert len(storage.objects) == 1
    assert len(queue.enqueued) == 1


async def test_same_key_different_file_conflicts(service: IngestService) -> None:
    await service.ingest(
        UploadCommand(filename="a.pdf", data=PDF, idempotency_key="key-1"), correlation_id=None
    )
    with pytest.raises(IdempotencyKeyConflictError):
        await service.ingest(
            UploadCommand(filename="b.pdf", data=make_pdf(pages=2), idempotency_key="key-1"),
            correlation_id=None,
        )


async def test_lost_insert_race_returns_winner_and_cleans_up(
    service: IngestService, repo: FakeRepository, storage: FakeStorage, queue: FakeQueue
) -> None:
    # Another request with the same key and file commits between our lookup and insert.
    winner_result = await IngestService(
        repository=FakeRepository(),
        storage=FakeStorage(),
        inspector=FakeInspector(),
        queue=FakeQueue(),
        limits=IngestLimits(max_bytes=10_000, max_pages=3),
    ).ingest(UploadCommand(filename="a.pdf", data=PDF, idempotency_key="k"), correlation_id=None)
    repo.race_winner = winner_result.document

    result = await service.ingest(
        UploadCommand(filename="a.pdf", data=PDF, idempotency_key="k"), correlation_id=None
    )

    assert result.replayed
    assert result.document.id == winner_result.document.id
    assert storage.objects == {}  # our orphan upload was removed
    assert queue.enqueued == []


async def test_db_failure_removes_uploaded_object(
    service: IngestService, repo: FakeRepository, storage: FakeStorage
) -> None:
    repo.fail_add_with = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        await service.ingest(UploadCommand(filename="x", data=PDF), correlation_id=None)
    assert storage.objects == {}


async def test_enqueue_failure_still_accepts_document(
    service: IngestService, repo: FakeRepository, queue: FakeQueue
) -> None:
    queue.fail = True
    result = await service.ingest(UploadCommand(filename="x", data=PDF), correlation_id=None)
    # Row is committed; the sweeper (week 3) will enqueue it later.
    assert result.document.id in repo.documents


async def test_filename_is_sanitised(service: IngestService) -> None:
    result = await service.ingest(
        UploadCommand(filename="../../secret/inv.pdf", data=PDF), correlation_id=None
    )
    assert result.document.original_filename == "inv.pdf"
    assert "secret" not in result.document.storage_key


async def test_replay_returns_original_even_if_status_moved_on(
    service: IngestService, repo: FakeRepository
) -> None:
    cmd = UploadCommand(filename="inv.pdf", data=PDF, idempotency_key="key-2")
    first = await service.ingest(cmd, correlation_id=None)
    repo.documents[first.document.id] = replace(first.document, status=DocumentStatus.COMPLETED)

    second = await service.ingest(cmd, correlation_id=None)
    assert second.document.status is DocumentStatus.COMPLETED
