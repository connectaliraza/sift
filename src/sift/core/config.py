"""Application settings (12-factor: environment variables only).

The app fails fast at startup if a required setting is missing or invalid.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    # --- runtime
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    # --- security
    api_key: SecretStr
    webhook_signing_secret: SecretStr

    # --- infrastructure
    database_url: str
    redis_url: str
    s3_endpoint_url: str | None = None  # None -> real AWS S3
    s3_bucket: str = "sift-documents"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str = "us-east-1"

    # --- LLM (used from week 2)
    llm_model: str = "ollama/qwen2.5:3b"
    llm_api_base: str | None = "http://host.docker.internal:11434"
    llm_timeout_s: int = 180

    # --- limits / behaviour
    max_upload_mb: int = Field(default=10, ge=1, le=100)
    max_pages: int = Field(default=10, ge=1, le=200)
    review_threshold: float = Field(default=0.80, ge=0.0, le=1.0)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    # Required values come from the environment (pydantic-settings).
    return Settings()
