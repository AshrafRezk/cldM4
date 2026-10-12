"""POST /v1/audio/transcriptions — exclusive whisper slot + scope checks."""

from __future__ import annotations

import io
import wave

import pytest

from app.errors import CloudiatorError


def _wav_bytes(frames: int = 1600) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


async def test_transcriptions_without_scope_is_403(make_client, install_key):
    _record, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"


async def test_transcriptions_happy_path_uses_exclusive_slot(
    make_client, install_key, monkeypatch
):
    calls: list[str] = []

    async def fake_transcribe(data, *, settings, scheduler, **kwargs):
        calls.append("ran")
        return {"text": "hello from caller", "language": "en", "model": "whisper-large-v3-turbo"}

    monkeypatch.setattr("app.voice_routes.transcribe_bytes", fake_transcribe)
    _record, headers = install_key(capabilities=["transcriptions"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
            data={"language": "en"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "hello from caller"
    assert body["model"] == "whisper-large-v3-turbo"
    assert calls == ["ran"]


async def test_whisper_refuses_missing_model_dir(settings):
    import dataclasses

    from app import whisper

    broken = dataclasses.replace(settings, whisper_model_path="/no/such/whisper/model")
    with pytest.raises(CloudiatorError) as exc:
        whisper.assert_whisper_ready(broken)
    assert exc.value.status_code == 503
