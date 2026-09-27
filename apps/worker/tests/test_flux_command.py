"""FLUX argv is local, 4-bit, and --low-ram. The sync chat loop cannot run it."""

from __future__ import annotations

import dataclasses
import os
import stat

import pytest

from app.config import get_settings
from app.errors import CloudiatorError
from tools.image_generate.handler import generate, image_request, mflux_command


def _settings(model: str, *, low_ram: bool = True):
    return dataclasses.replace(get_settings(), mflux_model_path=model, mflux_low_ram=low_ram)


def test_command_pins_the_local_directory_and_low_ram(tmp_path, monkeypatch):
    model = tmp_path / "flux-schnell-4bit"
    model.mkdir()
    binary = tmp_path / "mflux-generate"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr("tools.image_generate.handler.mflux_binary", lambda: str(binary))
    argv = mflux_command(
        _settings(str(model)),
        image_request({"prompt": "a red bicycle", "seed": 7}),
        "/tmp/out.png",
    )
    assert argv[:3] == [str(binary), "--model", str(model)]
    assert "--base-model" in argv and "schnell" in argv
    assert "--low-ram" in argv
    assert "--quantize" not in argv
    assert "--path" not in argv
    assert "huggingface.co" not in " ".join(argv)


def test_a_missing_model_directory_does_not_build_a_command(tmp_path):
    with pytest.raises(CloudiatorError) as caught:
        mflux_command(
            _settings(str(tmp_path / "missing")),
            image_request({"prompt": "a red bicycle"}),
            "/tmp/out.png",
        )
    assert caught.value.status_code == 503
    assert "download" in caught.value.message


def test_edges_above_1024_are_rejected():
    with pytest.raises(CloudiatorError):
        image_request({"prompt": "a red bicycle", "size": "2048x2048"})


async def test_generate_writes_an_artifact(tmp_path, monkeypatch):
    from app import main

    model = tmp_path / "flux-schnell-4bit"
    model.mkdir()
    binary = tmp_path / "mflux-generate"
    binary.write_text(
        "#!/bin/sh\n"
        "out=\n"
        "prev=\n"
        'for arg in "$@"; do\n'
        '  if [ "$prev" = "--output" ]; then out="$arg"; fi\n'
        '  prev="$arg"\n'
        "done\n"
        "printf '\\211PNG\\r\\n\\032\\n' > \"$out\"\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr("tools.image_generate.handler.mflux_binary", lambda: str(binary))
    monkeypatch.setattr(
        main.jobs,
        "settings",
        _settings(str(model)),
    )
    result = await generate(
        {"prompt": "a red bicycle"},
        settings=_settings(str(model)),
        artifacts=main.artifacts,
        scheduler=main.scheduler,
    )
    assert result["id"]
    assert result["url"].startswith("https://api.cloudiator.test/artifacts/")
    assert os.path.isfile(os.path.join(main.settings.artifact_dir, result["id"] + ".png"))


async def test_the_chat_loop_refuses_flux(settings):
    from app.auth import KeyRecord
    from app.tool_loop import ToolRunner, load_registry

    record = KeyRecord(
        key_id="k",
        tenant_id="t",
        public_id="pub",
        secret_hash="h",
        name="n",
        preset=None,
        capabilities=frozenset({"image_generation", "chat"}),
        models=(),
        tools=(),
        max_tokens=512,
        max_context=4096,
        rpm=30,
        daily_token_budget=None,
        allowed_origins=(),
        salesforce_org_id=None,
        log_prompts=False,
        strip_exif=True,
        force_no_stream=True,
        max_response_bytes=1_048_576,
    )
    runner = ToolRunner(settings, load_registry(), maps=None)
    result = await runner.execute("flux_generate", {"prompt": "a red bicycle"}, record)
    assert result["error"] == "not_supported"
