"""The operator CLI's configuration loading.

`~/Cloudiator/.env` is the single source of truth on the Mini. The LaunchAgent
wrapper reads it for the worker via scripts/lib/load-env.sh. An interactive
shell does not, so the CLI reads it itself: "DATABASE_URL is not set" about a
file that plainly sets it is a confusing way to learn the difference.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.dbtool import load_env_file

REPO_ROOT = Path(__file__).resolve().parents[3]
LOAD_ENV_PROOF = REPO_ROOT / "scripts" / "lib" / "test-load-env.sh"


@pytest.fixture()
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "DATABASE_URL=postgresql://u:p@ep-x-pooler.eu-west-2.aws.neon.tech/neondb",
                "export ADMIN_TOKEN=exported-token",
                'CF_ACCESS_AUD="quoted-aud"',
                "NOMINATIM_USER_AGENT=Cloudiator/0.1 (someone@example.com)",
                "ALREADY_SET=from-the-file",
                "AFTER_UA=still-loaded",
                "not-a-variable-line",
            ]
        )
    )
    return path


def test_it_fills_in_what_the_shell_did_not_set(env_file, monkeypatch):
    for name in (
        "DATABASE_URL",
        "ADMIN_TOKEN",
        "CF_ACCESS_AUD",
        "NOMINATIM_USER_AGENT",
        "AFTER_UA",
    ):
        monkeypatch.delenv(name, raising=False)

    loaded = load_env_file(env_file)

    assert "DATABASE_URL" in loaded
    assert os.environ["DATABASE_URL"].endswith("/neondb")
    # `export FOO=bar` is how half the world writes a dotenv line.
    assert os.environ["ADMIN_TOKEN"] == "exported-token"
    assert os.environ["CF_ACCESS_AUD"] == "quoted-aud"
    # A value with spaces and parentheses survives intact: the Nominatim
    # User-Agent is exactly that shape, and a mangled one gets the home IP blocked.
    assert os.environ["NOMINATIM_USER_AGENT"] == "Cloudiator/0.1 (someone@example.com)"
    # A failed `source` in zsh stops at that line; the parser must not.
    assert os.environ["AFTER_UA"] == "still-loaded"
    assert "not-a-variable-line" not in loaded


def test_the_environment_wins_over_the_file(env_file, monkeypatch):
    """So a one-off override on the command line still works."""
    monkeypatch.setenv("ALREADY_SET", "from-the-shell")

    loaded = load_env_file(env_file)

    assert "ALREADY_SET" not in loaded
    assert os.environ["ALREADY_SET"] == "from-the-shell"


def test_a_missing_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == []


def test_shell_loader_accepts_the_nominatim_user_agent():
    """The LaunchAgent wrapper uses the same parser. Prove it on bash."""
    proof = subprocess.run(
        ["bash", str(LOAD_ENV_PROOF)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proof.returncode == 0, proof.stdout + proof.stderr
    assert "PASS load-env.sh" in proof.stdout
