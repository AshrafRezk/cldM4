"""Browser call: link → page → start → turns → ready_to_commit, speech stubbed."""

from __future__ import annotations

import os
import uuid

import pytest

from app import main
from app.voice import speech
from tests.voice_fixture import intake


@pytest.fixture()
def fake_speech(monkeypatch):
    heard: list[str] = []
    calls = {"stt": 0}

    async def transcribe(audio, *, language, settings):
        calls["stt"] += 1
        return heard.pop(0) if audio else ""

    async def synthesize_data_url(text, **kwargs):
        return "data:audio/mp4;base64,AAAA"

    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "synthesize_data_url", synthesize_data_url)
    return heard, calls


async def publish_and_link(client, script=None):
    script = script or intake(id="web-" + uuid.uuid4().hex[:8], inbound_numbers=[])
    assert (await client.post("/v1/voice/scripts", json=script)).status_code == 200
    made = await client.post(f"/v1/voice/scripts/{script['id']}/web-link")
    assert made.status_code == 200, made.text
    url = made.json()["url"]
    assert url.startswith("https://api.cloudiator.test/v1/voice/web/cl_")
    return script, url.removeprefix("https://api.cloudiator.test")


async def answer(client, path, turn, audio=b"RIFFfake"):
    listen = turn["listen"]
    return await client.post(
        f"{path}/turn",
        params={"call_id": turn["call_id"], "step": listen["step"], "attempt": listen["attempt"]},
        content=audio,
        headers={"Content-Type": "audio/wav"},
    )


async def test_full_browser_call(make_client, install_key, fake_speech):
    heard, _calls = fake_speech
    _record, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        _script, path = await publish_and_link(client)

    async with make_client() as anon:  # the caller has no key
        page = await anon.get(path)
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "Arabic inbound intake" in page.text
        assert "sk-cld" not in page.text

        turn = (await anon.post(f"{path}/start")).json()
        assert [c["text"][:6] for c in turn["clips"]] == ["مرحباً", "من فضل"]
        assert turn["clips"][0]["audio"].startswith("data:audio/mp4")
        assert turn["listen"]["step"] == "ask_name"

        heard.extend(["سارة أحمد", "حجز موعد", "01012345678"])
        for _ in range(3):
            response = await answer(anon, path, turn)
            assert response.status_code == 200, response.text
            turn = response.json()
        assert turn["done"] is True
        assert turn["heard"] == "01012345678"
        assert "شكراً" in turn["clips"][-1]["text"]

    async with make_client(headers) as client:
        sessions = (await client.get("/v1/voice/sessions", params={"status": "ready_to_commit"})).json()
    session = next(s for s in sessions["data"] if s["call_sid"] == turn["call_id"])
    assert session["from"] == "web"
    assert session["commit"]["records"][0]["fields"]["LastName"] == "سارة أحمد"


async def test_silence_is_not_transcribed_and_replays(make_client, install_key, fake_speech):
    _heard, calls = fake_speech
    _record, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        _script, path = await publish_and_link(client)
    async with make_client() as anon:
        turn = (await anon.post(f"{path}/start")).json()
        again = (await answer(anon, path, turn, audio=b"")).json()
    assert again["listen"] == {**turn["listen"], "attempt": 2}
    assert calls["stt"] == 1  # called, but with empty audio it returns "" without work


async def test_retry_replays_without_transcribing_twice(make_client, install_key, fake_speech):
    heard, calls = fake_speech
    _record, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        _script, path = await publish_and_link(client)
    async with make_client() as anon:
        turn = (await anon.post(f"{path}/start")).json()
        heard.append("Sara")
        first = (await answer(anon, path, turn)).json()
        second = (await answer(anon, path, turn)).json()
    assert first["clips"] == second["clips"]
    assert calls["stt"] == 1


async def test_bad_or_revoked_link_is_404(make_client, install_key, fake_speech):
    _record, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        script, path = await publish_and_link(client)
        assert (await client.post(f"/v1/voice/scripts/{script['id']}/web-link/revoke")).json()["revoked"] == 1
        missing = await client.post("/v1/voice/scripts/nope/web-link")
    assert missing.status_code == 404
    async with make_client() as anon:
        assert (await anon.get(path)).status_code == 404
        assert (await anon.post(f"{path}/start")).status_code == 404
        assert (await anon.get("/v1/voice/web/cl_forged")).status_code == 404


async def test_a_link_cannot_drive_another_scripts_call(make_client, install_key, fake_speech):
    _record, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        _a, path_a = await publish_and_link(client)
        _b, path_b = await publish_and_link(client)
    async with make_client() as anon:
        turn = (await anon.post(f"{path_a}/start")).json()
        stolen = await answer(anon, path_b, turn)
    assert stolen.status_code == 404


async def test_link_minting_needs_voice_scope(make_client, install_key):
    _record, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post("/v1/voice/scripts/anything/web-link")
    assert response.status_code == 403


async def test_missing_stt_is_a_503_not_a_silent_skip(make_client, install_key, monkeypatch):
    async def synthesize_data_url(text, **kwargs):
        return None

    async def broken(audio, *, language, settings):
        raise speech.SpeechUnavailable("whisper model is missing")

    monkeypatch.setattr(speech, "synthesize_data_url", synthesize_data_url)
    monkeypatch.setattr(speech, "transcribe", broken)
    _record, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        _script, path = await publish_and_link(client)
    async with make_client() as anon:
        turn = (await anon.post(f"{path}/start")).json()
        response = await answer(anon, path, turn)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "speech_unavailable"


async def test_oversized_audio_is_413(make_client, install_key, fake_speech):
    _record, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        _script, path = await publish_and_link(client)
    async with make_client() as anon:
        turn = (await anon.post(f"{path}/start")).json()
        response = await answer(anon, path, turn, audio=b"x" * (main.settings.voice_web_max_audio_bytes + 1))
    assert response.status_code == 413


@pytest.mark.skipif(not os.path.exists("/usr/bin/say"), reason="macOS say only")
async def test_real_tts_produces_cached_audio(tmp_path):
    first = await speech.synthesize("مرحباً", language="ar-EG", local_voice=None, cache_dir=str(tmp_path))
    assert first[4:8] == b"ftyp"  # an MP4/M4A container
    assert len(list(tmp_path.glob("*.m4a"))) == 1
    again = await speech.synthesize("مرحباً", language="ar-EG", local_voice=None, cache_dir=str(tmp_path))
    assert again == first


def test_voice_selection():
    assert speech.voice_for("ar-EG", None) == "Majed"
    assert speech.voice_for("en-US", None) == "Samantha"
    assert speech.voice_for("ar-EG", "Tarik") == "Tarik"
    assert speech.voice_for("fr-FR", None) is None
