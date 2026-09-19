from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra" / "launchagents" / "run-worker.sh"


def _dump(env_text: str, tmp_path: Path) -> list[str]:
    env_file = tmp_path / ".env"
    env_file.write_text(env_text)
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--dump-keys"],
        env={**os.environ, "CLOUDIATOR_ENV_FILE": str(env_file)},
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def test_wrapper_loads_unquoted_special_chars(tmp_path: Path) -> None:
    """Mini .env from .env.example is unquoted; zsh source dies on '?' and ()."""
    lines = _dump(
        "DATABASE_URL=postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/neondb?sslmode=require\n"
        "NOMINATIM_USER_AGENT=Cloudiator/0.1 (you@example.com)\n"
        "OLLAMA_MAX_LOADED_MODELS=2\n"
        "WEB_CONCURRENCY=1\n"
        "# comment\n"
        "export DEFAULT_MODEL=qwen3.5:9b\n",
        tmp_path,
    )
    assert lines[0] == (
        "postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/neondb?sslmode=require"
    )
    assert lines[1] == "Cloudiator/0.1 (you@example.com)"
    assert lines[2] == "2"
    assert lines[3] == "1"


def test_wrapper_strips_quotes(tmp_path: Path) -> None:
    lines = _dump(
        'DATABASE_URL="postgresql://u:p@h/db?sslmode=require"\n'
        'NOMINATIM_USER_AGENT="Cloudiator/0.1 (you@example.com)"\n'
        "OLLAMA_MAX_LOADED_MODELS=2\n"
        "WEB_CONCURRENCY=1\n",
        tmp_path,
    )
    assert lines[0] == "postgresql://u:p@h/db?sslmode=require"
    assert lines[1] == "Cloudiator/0.1 (you@example.com)"


def test_wrapper_missing_env_exits(tmp_path: Path) -> None:
    missing = tmp_path / "nope.env"
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--dump-keys"],
        env={**os.environ, "CLOUDIATOR_ENV_FILE": str(missing)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "missing env file" in result.stderr
