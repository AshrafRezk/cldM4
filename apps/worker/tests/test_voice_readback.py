"""Number answers are read back ("قلت 0 1 0 1…، صح كده؟") and confirmed."""

from __future__ import annotations

import base64
import dataclasses
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from app import main
from app.voice import speech
from app.voice.audio import VoiceAudio
from app.voice.engine import ScriptInvalid, VoiceEngine, digits_in, validate_script, yes_no
from app.voice.store import VoiceStore


def intake(**overrides):
    script = {
        "id": "rb-" + uuid.uuid4().hex[:6],
        "languages": ["ar-EG", "en-US"],
        "steps": [
            {"key": "mobile", "gather": True, "confirm": True, "max_attempts": 3, "next": "done",
             "say": {"ar-EG": "إيه رقم موبايلك؟", "en-US": "What is your mobile number?"}},
            {"key": "done", "say": {"ar-EG": "شكراً.", "en-US": "Thank you."}},
        ],
        "commit": {"records": [{"sobject": "Contact", "fields": {"MobilePhone": "{{mobile}}"}}]},
    }
    script.update(overrides)
    return script


@pytest.fixture()
def engine(tmp_path):
    return VoiceEngine(VoiceStore(str(tmp_path / "v.db")), public_base_url="https://api.test", ttl_days=7)


def begin(engine, language="ar-EG", **overrides):
    script = intake(**overrides)
    engine.store.upsert_script("t1", validate_script(script))
    call = "WB" + uuid.uuid4().hex
    engine.start_call(tenant_id="t1", script_id=script["id"], call_sid=call, from_label="web", language=language)
    return call


def say(engine, call, text):
    s = engine.store.session_by_call(call)
    return engine.on_gather(call_sid=call, step=s["current_step"], attempt=s["attempt"], speech=text, turn=s["turn"])


def gather_of(reply):
    return next(v["gather"] for v in reply["verbs"] if "gather" in v)


@pytest.mark.parametrize("text, expected", [
    ("أيوه صح", True), ("ايوة", True), ("تمام كده", True), ("yes that's right", True), ("oui", True),
    ("لأ غلط", False), ("مش صح", False), ("no", False), ("non", False),
    ("ممكن تعيد", None), ("01012345678", None),
    # as recognition actually wrote them on live calls
    ("ايو صحة", True), ("آه صحيح", True), ("تمامًا", True), ("ايوا يا فندم", True),
    ("ايه؟", None), ("قلت ايه", None), ("لأ مش كده", False), ("غلطانة", False),
])
def test_yes_no(text, expected):
    assert yes_no(text) is expected


def test_digits_in_handles_arabic_indic():
    assert digits_in("رقمي ٠١٠ 123") == "010123"


def test_confirm_only_on_questions():
    with pytest.raises(ScriptInvalid):
        validate_script(intake(steps=[{"key": "x", "say": "hi", "confirm": True}]))


def test_yes_keeps_the_number(engine):
    call = begin(engine)
    reply = say(engine, call, "01012345678")
    g = gather_of(reply)
    assert g["confirm_digits"] == "01012345678"
    assert g["prompt"] == "قلت 0 1 0 1 2 3 4 5 6 7 8، صح كده؟"
    say(engine, call, "أيوه مظبوط")
    s = engine.store.session_by_call(call)
    assert s["status"] == "ready_to_commit"
    assert s["commit_doc"]["records"][0]["fields"]["MobilePhone"] == "01012345678"


def test_no_asks_again_and_uses_an_attempt(engine):
    call = begin(engine, "en-US")
    say(engine, call, "0101 234")
    reply = say(engine, call, "no, that's wrong")
    assert reply["verbs"][0]["say"] == "Sorry, could you say it again?"
    assert reply["verbs"][0]["key"] == "__again__"
    g = gather_of(reply)
    assert g["prompt"] == "What is your mobile number?" and g["attempt"] == 2 and "confirm_digits" not in g


def test_saying_the_number_again_replaces_it(engine):
    call = begin(engine)
    say(engine, call, "0101234")
    reply = say(engine, call, "لأ 01012345678")  # "no" + the right number: a correction
    assert reply["verbs"][0]["key"] == "__again__", "an explicit no first asks again"
    reply = say(engine, call, "01012345678")
    assert gather_of(reply)["confirm_digits"] == "01012345678"
    reply = say(engine, call, "0122")  # said a different number at the confirmation
    assert gather_of(reply)["confirm_digits"] == "0122"


def test_no_digits_is_not_an_answer(engine):
    call = begin(engine)
    reply = say(engine, call, "مش فاكر والله")
    assert reply["verbs"][0]["key"] == "__again__" and gather_of(reply)["attempt"] == 2


def test_out_of_attempts_moves_on(engine):
    call = begin(engine, "en-US")
    for text in ["0101", "no", "0102", "no"]:
        say(engine, call, text)
    say(engine, call, "0103")
    reply = say(engine, call, "no")
    assert reply["verbs"][-1] == {"hangup": True}
    s = engine.store.session_by_call(call)
    assert s["status"] == "ready_to_commit"
    assert s["commit_doc"]["records"][0]["fields"]["MobilePhone"] == "", '"no" is never stored as the number'


def test_readback_lines_are_rendered_per_voice():
    lines = main.voice_audio.lines(validate_script(intake()))
    keys = [l["key"] for l in lines if l["language"] == "ar-EG"]
    assert {"__said__", "__right__", "__again__"} <= set(keys)
    assert [k for k in keys if k.startswith("__digit_")] == [f"__digit_{d}" for d in range(10)]
    digits = {l["key"]: l["text"] for l in lines if l["language"] == "ar-EG"}
    assert digits["__digit_2"] == "اتنين" and digits["__said__"] == "قلت"


@pytest.mark.skipif(not Path(main.settings.ffmpeg_bin).exists(), reason="needs ffmpeg")
async def test_the_readback_is_stitched_from_rendered_pieces(tmp_path):
    (tmp_path / "python").write_text("")
    audio = VoiceAudio(dataclasses.replace(main.settings, voice_tts_engine="voicetut",
                                           voicetut_python=str(tmp_path / "python"),
                                           voice_audio_dir=str(tmp_path / "audio")))
    clean = validate_script(intake())
    for line in audio.lines(clean):
        if line["language"] == "ar-EG":
            path = audio.rendered_path(line["speaker"], line["language"], line["text"])
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([main.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-f", "lavfi",
                            "-i", "sine=frequency=300:duration=0.3", "-c:a", "aac", str(path)], check=True)
    data_url, source = await audio.confirm_clip(tenant_id="t1", script=clean, language="ar-EG",
                                                persona=None, digits="0101")
    assert source == "rendered" and data_url.startswith("data:audio/mp4;base64,")
    stitched = tmp_path / "stitched.m4a"
    stitched.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
    probe = subprocess.run([main.settings.ffmpeg_bin, "-i", str(stitched)], capture_output=True, text=True).stderr
    seconds = sum(60 ** i * float(x) for i, x in enumerate(reversed(probe.split("Duration: ")[1].split(",")[0].split(":"))))
    assert 6 * 0.3 < seconds < 6 * 0.3 + 1.5, "said + 4 digits + right, with short gaps"
    missing = await audio.confirm_clip(tenant_id="t1", script=clean, language="en-US", persona=None, digits="1")
    assert missing == (None, "pending")


async def test_browser_call_reads_the_number_back(make_client, install_key, monkeypatch):
    heard = iter(["01012345678", "أيوه"])

    async def transcribe(audio, *, language, settings):
        return next(heard)

    async def synthesize(text, **kwargs):
        return b"fallback-audio"

    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "synthesize", synthesize)
    _r, headers = install_key(capabilities=["voice"])
    script = intake(languages=["ar-EG"], steps=[
        {"key": "mobile", "gather": True, "confirm": True, "next": None, "say": "إيه رقم موبايلك؟"}])
    async with make_client(headers) as client:
        await client.post("/v1/voice/scripts", json=script)
        path = (await client.post(f"/v1/voice/scripts/{script['id']}/web-link")).json()["url"].removeprefix(
            "https://api.cloudiator.test")
    async with make_client() as anon:
        t = (await anon.post(f"{path}/start")).json()
        for _ in range(2):
            l = t["listen"]
            t = (await anon.post(f"{path}/turn", params={"call_id": t["call_id"], "step": l["step"],
                 "attempt": l["attempt"], "turn": l["turn"]}, content=b"RIFF")).json()
            if not t["done"]:
                assert t["clips"][0]["text"] == "قلت 0 1 0 1 2 3 4 5 6 7 8، صح كده؟"
                assert t["clips"][0]["audio"], "say engine: spoken whole, not silent"
        assert t["done"] is True
