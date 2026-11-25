"""Per-process resources for Celery workers (sync DB engine, storage client)."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from sift.adapters.s3_storage import S3ObjectStorage
from sift.core.config import Settings
from sift.db.session import make_sync_engine, make_sync_sessionmaker

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None
_storage: S3ObjectStorage | None = None


def init(settings: Settings) -> None:
    global _engine, _sessionmaker, _storage  # noqa: PLW0603 - process-wide singletons
    _engine = make_sync_engine(settings.database_url)
    _sessionmaker = make_sync_sessionmaker(_engine)
    _storage = S3ObjectStorage.from_settings(settings)


def close() -> None:
    if _engine is not None:
        _engine.dispose()


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction per unit of work: commit on success, roll back on error."""
    if _sessionmaker is None:
        raise RuntimeError("Worker resources not initialised; call resources.init() first.")
    with _sessionmaker.begin() as session:
        yield session


def storage() -> S3ObjectStorage:
    if _storage is None:
        raise RuntimeError("Worker resources not initialised; call resources.init() first.")
    return _storage
