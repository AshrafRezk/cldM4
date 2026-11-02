"""Debug capture: off by default; on, every answer window is kept 24 h on the Mini."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

from app import main
from app.voice import debug, speech
from tests.voice_fixture import bilingual


@pytest.fixture()
def debug_on():
    """Settings are frozen on purpose; flip the one flag for this test only."""
    object.__setattr__(main.settings, "voice_debug_audio", True)
    yield Path(main.settings.voice_debug_dir)
    object.__setattr__(main.settings, "voice_debug_audio", False)


@pytest.fixture()
def fake_speech(monkeypatch):
    calls = []

    async def transcribe(audio, *, language, settings):
        calls.append(len(audio))
        return "Sara" if audio else ""

    async def synthesize(text, **kwargs):
        return b"fallback-audio"

    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "synthesize", synthesize)
    return calls


async def start(make_client, install_key):
    _r, headers = install_key(capabilities=["voice"])
    script = bilingual(id="dbg-" + uuid.uuid4().hex[:6], voices={})
    async with make_client(headers) as client:
        await client.post("/v1/voice/scripts", json=script)
        path = (await client.post(f"/v1/voice/scripts/{script['id']}/web-link")).json()["url"].removeprefix(
            "https://api.cloudiator.test")
    return path


def params(turn):
    l = turn["listen"]
    return {"call_id": turn["call_id"], "step": l["step"], "attempt": l["attempt"], "turn": l["turn"]}


async def test_debug_is_off_by_default(make_client, install_key, fake_speech):
    path = await start(make_client, install_key)
    async with make_client() as anon:
        t = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
        assert t["listen"]["debug"] is False
        await anon.post(f"{path}/turn", params=params(t), content=b"RIFF-window",
                        headers={"X-Voice-Detected": "0", "X-Voice-Diag": "{}"})
    assert fake_speech == [11], "without debug the page's audio is used as sent"
    assert not any(Path(main.settings.voice_debug_dir).glob("*")) if Path(main.settings.voice_debug_dir).exists() else True


async def test_a_missed_answer_is_saved_but_still_counts_as_silence(make_client, install_key, fake_speech, debug_on):
    path = await start(make_client, install_key)
    diag = {"ended": "no_speech_before_timeout", "noise_floor": 0.02, "peak": 0.04, "threshold": 0.06, "detected": False}
    async with make_client() as anon:
        t = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
        assert t["listen"]["debug"] is True
        nxt = (await anon.post(f"{path}/turn", params=params(t), content=b"RIFF-full-window",
                               headers={"X-Voice-Detected": "0", "X-Voice-Diag": json.dumps(diag)})).json()
    assert nxt["listen"]["attempt"] == 2, "the call behaves exactly as without debug"
    note = sorted(debug_on.glob(f"*{t['call_id'][:14]}*.json"))[-1]
    saved = json.loads(note.read_text())
    assert saved["diag"]["ended"] == "no_speech_before_timeout" and saved["heard"] == ""
    assert saved["transcribed"] is False
    assert note.with_suffix(".wav").read_bytes() == b"RIFF-full-window"
    assert oct(os.stat(note).st_mode & 0o777) == "0o600"


async def test_a_heard_answer_is_saved_with_what_whisper_heard(make_client, install_key, fake_speech, debug_on):
    path = await start(make_client, install_key)
    async with make_client() as anon:
        t = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
        await anon.post(f"{path}/turn", params=params(t), content=b"RIFF-speech",
                        headers={"X-Voice-Detected": "1", "X-Voice-Diag": json.dumps({"detected": True})})
    note = sorted(debug_on.glob(f"*{t['call_id'][:14]}*.json"))[-1]
    assert json.loads(note.read_text())["heard"] == "Sara"


def test_debug_files_older_than_a_day_are_deleted(tmp_path):
    from types import SimpleNamespace

    settings = SimpleNamespace(voice_debug_dir=str(tmp_path))
    old, new = tmp_path / "old.wav", tmp_path / "new.wav"
    old.write_bytes(b"x"); new.write_bytes(b"y")
    two_days = time.time() - 2 * 86400
    os.utime(old, (two_days, two_days))
    assert debug.purge(settings) == 1
    assert not old.exists() and new.exists()
