"""Create the storage bucket if it doesn't exist (idempotent, retries until ready).

Runs as the one-shot ``storage-init`` Compose service:
    python -m sift.scripts.ensure_bucket
"""

import sys
import time

import structlog
from botocore.exceptions import BotoCoreError, ClientError

from sift.adapters.s3_storage import S3ObjectStorage
from sift.core.config import get_settings
from sift.core.logging import configure_logging

log = structlog.get_logger(__name__)


def main(attempts: int = 30, delay_s: float = 2.0) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    storage = S3ObjectStorage.from_settings(settings)

    for attempt in range(1, attempts + 1):
        try:
            created = storage.ensure_bucket()
        except (BotoCoreError, ClientError) as exc:
            log.info("storage.not_ready", attempt=attempt, error=type(exc).__name__)
            time.sleep(delay_s)
            continue
        log.info("storage.bucket_ready", bucket=settings.s3_bucket, created=created)
        return 0

    log.error("storage.unreachable", attempts=attempts)
    return 1


if __name__ == "__main__":
    sys.exit(main())
