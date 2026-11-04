"""Recording studio: a person's voice for each line, saved on the Mini."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid

import pytest

from app import main
from app.voice import speech
from tests.voice_fixture import bilingual

HAS_FFMPEG = bool(shutil.which("ffmpeg") or os.path.exists("/opt/homebrew/bin/ffmpeg"))


@pytest.fixture()
def fake_tts(monkeypatch):
    async def synthesize(text, **kwargs):
        return b"fallback-audio"

    async def transcribe(audio, *, language, settings, digits_hint=False):
        return "Sara" if audio else ""

    monkeypatch.setattr(speech, "synthesize", synthesize)
    monkeypatch.setattr(speech, "transcribe", transcribe)


async def setup_script(make_client, headers):
    script = bilingual(id="st-" + uuid.uuid4().hex[:8])
    async with make_client(headers) as client:
        assert (await client.post("/v1/voice/scripts", json=script)).status_code == 200
        studio = (await client.post(f"/v1/voice/scripts/{script['id']}/studio-link")).json()
        call = (await client.post(f"/v1/voice/scripts/{script['id']}/web-link")).json()
    strip = lambda url: url.removeprefix("https://api.cloudiator.test")  # noqa: E731
    return script, strip(studio["url"]), strip(call["url"])


async def test_studio_lists_every_line_in_both_languages(make_client, install_key, fake_tts):
    _r, headers = install_key(capabilities=["voice"])
    _script, studio, _call = await setup_script(make_client, headers)
    assert "/v1/voice/studio/st_" in studio
    async with make_client() as anon:
        page = await anon.get(studio)
        assert page.status_code == 200 and "Recording studio" in page.text
        lines = (await anon.get(f"{studio}/lines")).json()
    assert lines["languages"] == ["ar-EG", "en-US"]
    assert len(lines["lines"]) == 14
    greeting = next(l for l in lines["lines"] if l["key"] == "greeting" and l["language"] == "ar-EG")
    assert greeting["label"] == "Greeting" and greeting["source"] == "fallback"
    assert {l["key"] for l in lines["lines"]} >= {"__hold__", "__fail__"}


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
async def test_a_saved_take_is_what_callers_hear(make_client, install_key, fake_tts, tmp_path):
    _r, headers = install_key(capabilities=["voice"])
    _script, studio, call = await setup_script(make_client, headers)
    take = tmp_path / "take.webm"
    # What MediaRecorder sends from Chrome: Opus in WebM, with a little lead-in silence.
    subprocess.run([main.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=mono:d=0.5", "-f", "lavfi", "-i", "sine=frequency=300:duration=1",
                    "-filter_complex", "[0][1]concat=n=2:v=0:a=1", "-c:a", "libopus", str(take)], check=True)
    async with make_client() as anon:
        saved = await anon.put(f"{studio}/recordings/greeting/ar-EG", content=take.read_bytes(),
                               headers={"Content-Type": "audio/webm"})
        assert saved.status_code == 200, saved.text
        lines = (await anon.get(f"{studio}/lines")).json()["lines"]
        assert next(l for l in lines if l["key"] == "greeting" and l["language"] == "ar-EG")["source"] == "recording"
        current = (await anon.get(f"{studio}/audio/greeting/ar-EG")).json()
        assert current["source"] == "recording" and current["audio"].startswith("data:audio/mp4")

        turn = (await anon.post(f"{call}/start", params={"lang": "ar-EG"})).json()
        # The script picked Hadeer (female) for Arabic and nothing is rendered yet:
        # the next line waits for her natural voice rather than speaking as Majed.
        assert [c["source"] for c in turn["clips"]] == ["recording", "pending"]
        await anon.post(f"{call}/hangup", params={"call_id": turn["call_id"]})

        assert (await anon.delete(f"{studio}/recordings/greeting/ar-EG")).json() == {"deleted": True}
        assert (await anon.get(f"{studio}/audio/greeting/ar-EG")).json()["source"] == "pending"

    tenant = main.voice.store.web_link(studio.rsplit("/", 1)[1], prefix="st_")[0]
    assert tenant  # the studio link resolves to the publishing tenant


async def test_studio_rejects_bad_lines_and_audio(make_client, install_key, fake_tts):
    _r, headers = install_key(capabilities=["voice"])
    _script, studio, _call = await setup_script(make_client, headers)
    async with make_client() as anon:
        assert (await anon.put(f"{studio}/recordings/nope/ar-EG", content=b"x")).status_code == 404
        assert (await anon.put(f"{studio}/recordings/greeting/fr-FR", content=b"x")).status_code == 404
        if HAS_FFMPEG:
            bad = await anon.put(f"{studio}/recordings/greeting/ar-EG", content=b"not audio")
            assert bad.status_code == 400


async def test_call_links_and_studio_links_do_not_mix(make_client, install_key, fake_tts):
    _r, headers = install_key(capabilities=["voice"])
    _script, studio, call = await setup_script(make_client, headers)
    call_token = call.rsplit("/", 1)[1]
    studio_token = studio.rsplit("/", 1)[1]
    async with make_client() as anon:
        assert (await anon.get(f"/v1/voice/studio/{call_token}")).status_code == 404
        assert (await anon.get(f"/v1/voice/web/{studio_token}")).status_code == 404
        assert (await anon.get("/v1/voice/studio/st_forged")).status_code == 404


async def test_studio_links_expire_after_a_week(make_client, install_key, fake_tts, monkeypatch):
    _r, headers = install_key(capabilities=["voice"])
    _script, studio, _call = await setup_script(make_client, headers)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 8 * 86400)
    async with make_client() as anon:
        assert (await anon.get(f"{studio}/lines")).status_code == 404


async def test_minting_a_studio_link_needs_voice(make_client, install_key):
    _r, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        assert (await client.post("/v1/voice/scripts/x/studio-link")).status_code == 403
