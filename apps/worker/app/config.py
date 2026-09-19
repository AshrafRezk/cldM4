"""Environment-backed settings. Secrets never go in git; Mini file is ~/Cloudiator/.env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_ENV_FILE = os.environ.get(
    "CLOUDIATOR_ENV_FILE",
    str(Path.home() / "Cloudiator" / ".env"),
)


def _env_file() -> str | None:
    path = Path(_DEFAULT_ENV_FILE)
    if path.is_file():
        return str(path)
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file(),
        extra="ignore",
        case_sensitive=False,
    )

    cloudiator_env: str = "production"
    host: str = "127.0.0.1"
    port: int = 8080
    public_base_url: str = "http://127.0.0.1:8080"

    ollama_host: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3.5:9b"
    embed_model: str = "nomic-embed-text"
    # Only set after ollama show confirms vision. qwen3.5:9b library page lists image input.
    default_model_vision: bool = True
    ollama_max_loaded_models: int = 2

    num_ctx: int = 4096
    max_tokens_default: int = 512
    max_num_ctx: int = 8192

    sync_deadline_seconds: float = 90.0
    embeddings_timeout_seconds: float = 15.0
    metal_lock_wait_seconds: float = 2.0
    think: bool = False  # Qwen3.5: keep false so chat does not stall in <think>

    vision_max_edge_px: int = 1024
    vision_max_images: int = 4
    vision_max_bytes: int = 25 * 1024 * 1024
    vision_fetch_timeout_seconds: float = 10.0
    vision_jpeg_quality: int = 85
    vision_tokens_per_image: int = 512

    artifact_dir: Path = Field(default_factory=lambda: Path.home() / "Cloudiator" / "artifacts")
    min_free_disk_gb: float = 10.0
    hard_stop_disk_gb: float = 5.0

    pid_file: Path = Field(default_factory=lambda: Path.home() / "Cloudiator" / "worker.pid")

    health_rpm: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
