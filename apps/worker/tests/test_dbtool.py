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

from app.config import reset_settings_cache
from app.dbtool import (
    flush_local_key_cache,
    format_key_line,
    load_catalog,
    parse_key_ref,
    preset_label,
    resolve_capabilities,
    load_env_file,
)

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


def test_voice_presets_include_voice():
    catalog = load_catalog()
    assert "voice" in catalog["capabilities"]
    assert "voice" in catalog["presets"]["voice_intake"]["capabilities"]
    assert catalog["presets"]["voice_intake"]["capabilities"] == ["chat", "voice"]
    assert "voice" in catalog["presets"]["salesforce_engineer"]["capabilities"]


def test_adding_voice_to_the_engineer_preset_keeps_that_label():
    """Keys minted before voice existed are the engineer list with voice missing."""
    current = [
        cap
        for cap in load_catalog()["presets"]["salesforce_engineer"]["capabilities"]
        if cap != "voice"
    ]
    updated = resolve_capabilities(current, add=["voice"])
    assert updated[-1] == "voice"
    assert preset_label(updated, "salesforce_engineer") == "salesforce_engineer"


def test_voice_intake_replaces_the_list():
    updated = resolve_capabilities(["chat", "embeddings", "tools.ocr"], preset="voice_intake")
    assert updated == ["chat", "voice"]
    assert preset_label(updated, None) == "voice_intake"


def test_unknown_capability_and_empty_scopes_are_refused():
    with pytest.raises(ValueError, match="unknown capability"):
        resolve_capabilities(["chat"], add=["root"])
    with pytest.raises(ValueError, match="no capabilities"):
        resolve_capabilities(["voice"], remove=["voice"])
    with pytest.raises(ValueError, match="unknown preset"):
        resolve_capabilities(["chat"], preset="not_a_preset")


def test_a_full_key_yields_only_the_public_id():
    secret = "this-secret-must-not-leak"
    public, full = parse_key_ref(f"sk-cld-abcdefghij2k_{secret}")
    assert public == "abcdefghij2k"
    assert full is True
    assert secret not in public

    with pytest.raises(ValueError) as exc:
        parse_key_ref(f"sk-cld-not-a-valid_{secret}")
    assert secret not in str(exc.value)
    assert "not-a-valid" not in str(exc.value)


def test_list_line_flags_a_key_without_voice():
    line = format_key_line(
        {
            "public_id": "abcdefghij2k",
            "revoked_at": None,
            "tenant": "merck",
            "rpm": 30,
            "preset": "salesforce_engineer",
            "name": "Merck",
            "capabilities": ["chat", "embeddings"],
        }
    )
    assert "voice=NO" in line
    assert "voice" not in line.split("voice=NO", 1)[1].split("\n", 1)[0]
    assert "chat, embeddings" in line


def test_flush_skips_the_network_without_a_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    reset_settings_cache()
    try:
        called = []
        text = flush_local_key_cache(opener=lambda request: called.append(request) or (200, "{}"))
    finally:
        reset_settings_cache()
    assert called == []
    assert "ADMIN_TOKEN" in text
    assert "60 seconds" in text


def test_flush_posts_only_to_loopback_and_hides_the_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "local-break-glass")
    monkeypatch.setenv("PORT", "8080")
    reset_settings_cache()
    seen = {}

    def opener(request):
        seen["url"] = request.full_url
        seen["token"] = request.get_header("X-admin-token")
        return 200, '{"flushed": 1, "ttl_seconds": 60}'

    try:
        text = flush_local_key_cache(opener=opener)
    finally:
        reset_settings_cache()
    assert seen["url"] == "http://127.0.0.1:8080/v1/admin/cache/flush"
    assert seen["token"] == "local-break-glass"
    assert "local-break-glass" not in text
    assert "flushed" in text


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
