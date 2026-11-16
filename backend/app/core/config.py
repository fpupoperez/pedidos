"""Process settings. Defaults are safe for tests."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment configuration for the API and the worker.

    Extra variables are rejected so a typo does not silently change behavior.
    """

    model_config = SettingsConfigDict(extra="forbid", env_file=None)

    database_url: str = "postgresql+psycopg://orders:orders@localhost:5432/orders"
    database_read_url: str = "postgresql+psycopg://orders_reader:orders_reader@localhost:5432/orders"
    nats_url: str = ""
    nats_delivery: str = "inline"
    nats_stream: str = "ORDERS"
    nats_subject: str = "orders.import"
    nats_worker: str = "orders_import_worker"
    data_dir: Path = Path("./data")
    llm_provider: str = "fake"
    llm_model: str = ""
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = 5
    question_row_limit: int = 200
    question_timeout_ms: int = 3000
    import_batch_size: int = 200
    auth_required: bool = False
    otel_service_name: str = "orders-api"
    otel_exporter_otlp_endpoint: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    max_upload_bytes: int = Field(default=5_242_880, description="Largest accepted CSV, in bytes.")


@lru_cache
def get_settings() -> Settings:
    """Return the process settings. The cache is cleared in tests that change the environment."""
    return Settings()
