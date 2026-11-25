"""S3-compatible object storage (RustFS locally, AWS S3 in production)."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from sift.core.config import Settings
from sift.domain.errors import TransientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class S3ObjectStorage:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3ObjectStorage":
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=(
                settings.s3_access_key.get_secret_value() if settings.s3_access_key else None
            ),
            aws_secret_access_key=(
                settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None
            ),
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=3,
                read_timeout=30,
                s3={"addressing_style": "path"},  # self-hosted S3 servers need path-style
            ),
        )
        return cls(client, settings.s3_bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as exc:
            raise TransientError("Object storage write failed.") from exc

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except (BotoCoreError, ClientError) as exc:
            raise TransientError("Object storage read failed.") from exc

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def check(self) -> None:
        self._client.head_bucket(Bucket=self._bucket)

    def ensure_bucket(self) -> bool:
        """Create the bucket if missing. Returns True if it was created."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return False
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                raise
        self._client.create_bucket(Bucket=self._bucket)
        return True
