"""One script, two languages: the caller's button decides what they hear and
which language whisper listens for. Audio comes from a recording, then a
publish-time render, then the macOS fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

from app import main
from app.voice import speech
from app.voice.audio import script_lines
from app.voice.engine import ScriptInvalid, validate_script
from tests.voice_fixture import bilingual, intake


@pytest.fixture()
def fake_speech(monkeypatch):
    seen = {"languages": []}

    async def transcribe(audio, *, language, settings):
        seen["languages"].append(language)
        return "Sara Ahmed" if audio else ""

    async def synthesize(text, **kwargs):
        return b"fallback-audio"

    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "synthesize", synthesize)
    return seen


def test_bilingual_script_validates_and_plain_strings_still_work():
    script = validate_script(bilingual())
    assert script["languages"] == ["ar-EG", "en-US"]
    assert script["language"] == "ar-EG"
    assert script["steps"][1]["say"]["en-US"] == "May I have your full name?"
    legacy = validate_script(intake())
    assert legacy["languages"] == ["ar-EG"]
    assert legacy["steps"][0]["say"]["ar-EG"].startswith("مرحباً")


def test_every_language_needs_text():
    script = bilingual()
    del script["steps"][2]["say"]["en-US"]
    with pytest.raises(ScriptInvalid) as info:
        validate_script(script)
    assert info.value.param == "steps[2].say"


@pytest.mark.parametrize("bad", [["arabic"], [], ["ar-EG", "ar-EG"], ["a", "b", "c", "d", "e"]])
def test_bad_language_lists(bad):
    with pytest.raises(ScriptInvalid):
        validate_script(bilingual(languages=bad))


def test_lines_cover_every_step_and_fail_message_per_language():
    lines = script_lines(validate_script(bilingual()))
    assert len(lines) == 2 * (4 + 2)
    assert {l["key"] for l in lines} >= {"greeting", "__fail__", "__hold__"}
    assert all(l["speaker"] == "Hadeer" for l in lines)


async def link_for(client, script):
    assert (await client.post("/v1/voice/scripts", json=script)).status_code == 200
    made = await client.post(f"/v1/voice/scripts/{script['id']}/web-link")
    return made.json()["url"].removeprefix("https://api.cloudiator.test")


async def test_english_button_hears_english_and_listens_in_english(make_client, install_key, fake_speech):
    _r, headers = install_key(capabilities=["voice"])
    script = bilingual(id="ci-" + uuid.uuid4().hex[:8])
    async with make_client(headers) as client:
        path = await link_for(client, script)
    async with make_client() as anon:
        page = (await anon.get(path)).text
        assert 'data-lang="ar-EG"' in page and 'data-lang="en-US"' in page
        assert "اتصل بالعربي" in page and "Call in English" in page

        turn = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
        assert turn["language"] == "en-US"
        assert [c["text"] for c in turn["clips"]] == ["Welcome to customer care.", "May I have your full name?"]
        assert turn["clips"][0]["source"] == "fallback"
        q = {"call_id": turn["call_id"], "step": "ask_name", "attempt": 1}
        turn = (await anon.post(f"{path}/turn", params=q, content=b"RIFF")).json()
        assert turn["clips"][0]["text"] == "Briefly, what is the problem?"
        assert fake_speech["languages"] == ["en-US"]
        hung = await anon.post(f"{path}/hangup", params={"call_id": turn["call_id"]})
        assert hung.json() == {"ended": True}

        arabic = (await anon.post(f"{path}/start", params={"lang": "ar-EG"})).json()
        assert arabic["clips"][1]["text"] == "ممكن تقولي اسمك بالكامل؟"
        wrong = await anon.post(f"{path}/start", params={"lang": "fr-FR"})
        assert wrong.status_code == 400

    async with make_client(headers) as client:
        data = (await client.get("/v1/voice/sessions")).json()["data"]
    langs = {s["call_id"] if "call_id" in s else s["call_sid"]: s["language"] for s in data}
    assert langs[turn["call_id"]] == "en-US"
    assert langs[arabic["call_id"]] == "ar-EG"


@pytest.fixture()
def engine(monkeypatch):
    """Pick a render engine for one test without spawning or calling it."""
    import dataclasses

    def _use(name, **extra):
        settings = dataclasses.replace(main.settings, voice_tts_engine=name, **extra)
        monkeypatch.setattr(main.voice_audio, "settings", settings)
        monkeypatch.setattr(main.voice_audio, "schedule", lambda script: 0)
        return main.voice_audio

    return _use


async def test_rendered_clip_beats_fallback(make_client, install_key, fake_speech, engine, tmp_path):
    engine("voicetut", voicetut_python=str(tmp_path / "python"))
    (tmp_path / "python").write_text("")
    _r, headers = install_key(capabilities=["voice"])
    script = bilingual(id="ci-" + uuid.uuid4().hex[:8])
    clean = validate_script(script)
    line = next(l for l in main.voice_audio.lines(clean) if l["key"] == "greeting" and l["language"] == "en-US")
    rendered = main.voice_audio.rendered_path(line["speaker"], line["language"], line["text"])
    rendered.parent.mkdir(parents=True, exist_ok=True)
    rendered.write_bytes(b"rendered-audio")
    async with make_client(headers) as client:
        path = await link_for(client, script)
        status = (await client.get(f"/v1/voice/scripts/{script['id']}/audio")).json()
    assert status["total"] == 12 and status["ready"] >= 1
    assert status["engine"] == "voicetut"
    async with make_client() as anon:
        turn = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
    assert [c["source"] for c in turn["clips"]] == ["rendered", "fallback"]


@pytest.mark.skipif(not shutil.which("ffmpeg") and not os.path.exists("/opt/homebrew/bin/ffmpeg"),
                    reason="needs ffmpeg")
async def test_a_staff_recording_wins_and_can_be_removed(make_client, install_key, fake_speech, tmp_path):
    _r, headers = install_key(capabilities=["voice"])
    script = bilingual(id="ci-" + uuid.uuid4().hex[:8])
    wav = tmp_path / "rec.wav"
    subprocess.run([main.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=1", str(wav)], check=True)
    base = f"/v1/voice/scripts/{script['id']}/recordings"
    async with make_client(headers) as client:
        path = await link_for(client, script)
        put = await client.put(f"{base}/ask_name/ar-EG", content=wav.read_bytes(),
                               headers={"Content-Type": "audio/wav"})
        assert put.status_code == 200, put.text
        assert (await client.put(f"{base}/nope/ar-EG", content=b"x")).status_code == 404
        assert (await client.put(f"{base}/ask_name/fr-FR", content=b"x")).status_code == 404
        bad = await client.put(f"{base}/greeting/ar-EG", content=b"not audio")
        assert bad.status_code == 400
    async with make_client() as anon:
        turn = (await anon.post(f"{path}/start", params={"lang": "ar-EG"})).json()
    assert [c["source"] for c in turn["clips"]] == ["fallback", "recording"]
    async with make_client(headers) as client:
        assert (await client.delete(f"{base}/ask_name/ar-EG")).json() == {"deleted": True}


async def test_recordings_are_tenant_scoped(make_client, install_key, fake_speech):
    _a, headers_a = install_key(capabilities=["voice"])
    _b, headers_b = install_key(capabilities=["voice"])
    script = bilingual(id="ci-" + uuid.uuid4().hex[:8])
    async with make_client(headers_a) as client:
        await client.post("/v1/voice/scripts", json=script)
    async with make_client(headers_b) as client:
        other = await client.put(f"/v1/voice/scripts/{script['id']}/recordings/ask_name/ar-EG", content=b"x")
        status = await client.get(f"/v1/voice/scripts/{script['id']}/audio")
    assert other.status_code == 404
    assert status.status_code == 404


def test_render_is_off_in_tests():
    assert main.voice_audio.schedule(validate_script(bilingual())) == 0


def test_engine_auto_prefers_azure_then_voicetut(engine, tmp_path):
    venv = tmp_path / "python"
    venv.write_text("")
    assert engine("auto", voicetut_python=str(tmp_path / "missing")).engine == "say"
    assert engine("auto", voicetut_python=str(venv)).engine == "voicetut"
    audio = engine("auto", voicetut_python=str(venv), azure_speech_key="k", azure_speech_region="westeurope")
    assert audio.engine == "azure"
    assert engine("azure").engine == "say"  # no key: off, not broken


def test_azure_voices_default_to_egyptian_and_british(engine):
    audio = engine("azure", azure_speech_key="k", azure_speech_region="westeurope")
    clean = validate_script(bilingual())  # voices say "Hadeer", a VoiceTut name
    assert audio.speaker_for(clean, "ar-EG") == "ar-EG-SalmaNeural"
    assert audio.speaker_for(clean, "en-US") == "en-GB-SoniaNeural"
    picked = validate_script(bilingual(voices={"ar-EG": "ar-EG-ShakirNeural", "en-US": "en-GB-RyanNeural"}))
    assert audio.speaker_for(picked, "ar-EG") == "ar-EG-ShakirNeural"
    assert audio.speaker_for(picked, "en-US") == "en-GB-RyanNeural"


async def test_azure_render_writes_mp3_clips_and_calls_play_them(
    make_client, install_key, fake_speech, engine, monkeypatch
):
    from app.voice import audio as audio_mod

    sent = []

    async def fake_azure(text, voice, settings):
        sent.append((voice, text))
        return b"ID3fake-mp3"

    monkeypatch.setattr(audio_mod, "azure_tts", fake_azure)
    audio = engine("azure", azure_speech_key="k", azure_speech_region="westeurope")
    script = bilingual(id="ci-" + uuid.uuid4().hex[:8])
    clean = validate_script(script)
    await audio._render(audio.lines(clean))
    assert len(sent) == 12
    assert ("ar-EG-SalmaNeural", "أهلاً بيك في خدمة العملاء.") in sent

    _r, headers = install_key(capabilities=["voice"])
    async with make_client(headers) as client:
        path = await link_for(client, script)
    async with make_client() as anon:
        turn = (await anon.post(f"{path}/start", params={"lang": "ar-EG"})).json()
    assert [c["source"] for c in turn["clips"]] == ["rendered", "rendered"]
    assert turn["clips"][0]["audio"].startswith("data:audio/mpeg;base64,")


async def test_azure_tts_refuses_bad_region_and_voice():
    from types import SimpleNamespace

    from app.voice.audio import azure_tts

    with pytest.raises(speech.SpeechUnavailable):
        await azure_tts("hi", "en-GB-SoniaNeural", SimpleNamespace(azure_speech_region="evil.com/x", azure_speech_key="k"))
    with pytest.raises(speech.SpeechUnavailable):
        await azure_tts("hi", "Hadeer", SimpleNamespace(azure_speech_region="westeurope", azure_speech_key="k"))
