"""TTS language/voice resolution and /v1/audio/speech."""

from __future__ import annotations

import pytest

from app.errors import CloudiatorError
from app.tts import FakeTtsProvider, normalize_language, resolve_voice


def test_normalize_language_aliases():
    assert normalize_language("en-US") == "en"
    assert normalize_language("ar") == "ar-EG"
    assert normalize_language("egyptian") == "ar-EG"
    assert normalize_language("fr-FR") == "fr"


def test_normalize_language_rejects_unknown():
    with pytest.raises(CloudiatorError) as exc:
        normalize_language("de")
    assert exc.value.status_code == 400


def test_default_voices():
    assert "Salma" in resolve_voice("ar-EG")
    assert "Jenny" in resolve_voice("en")
    assert "Denise" in resolve_voice("fr")


async def test_fake_provider_records_calls():
    provider = FakeTtsProvider(pcm=b"\x01\x00" * 100)
    pcm = await provider.synthesize("مرحبا", language="ar-EG")
    assert pcm.startswith(b"\x01\x00")
    assert provider.calls[0]["text"] == "مرحبا"
    assert provider.calls[0]["language"] == "ar-EG"


async def test_speech_route_returns_signed_wav(make_client, install_key, monkeypatch):
    from app import main
    from app.tts import FakeTtsProvider

    provider = FakeTtsProvider(pcm=b"\x00\x00" * 1600)
    monkeypatch.setattr("app.voice_routes.build_tts_provider", lambda settings: provider)
    _record, headers = install_key(capabilities=["tts"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Bonjour", "language": "fr"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "wav"
    assert body["language"] == "fr"
    assert body["url"].startswith("https://api.cloudiator.test/")
    assert provider.calls[0]["text"] == "Bonjour"


async def test_speech_without_scope_is_403(make_client, install_key):
    _record, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post("/v1/audio/speech", json={"input": "hi", "language": "en"})
    assert response.status_code == 403
