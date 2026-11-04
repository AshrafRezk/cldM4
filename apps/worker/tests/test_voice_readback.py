"""Number answers are read back as one grouped sentence and confirmed."""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import main
from app.voice import speech
from app.voice.audio import VoiceAudio
from app.voice.engine import (
    ScriptInvalid,
    VoiceEngine,
    confirm_text,
    digits_in,
    group_digits,
    validate_script,
    yes_no,
)
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


def say(engine, call, text, intent=None):
    s = engine.store.session_by_call(call)
    return engine.on_gather(
        call_sid=call, step=s["current_step"], attempt=s["attempt"], speech=text, turn=s["turn"], intent=intent
    )


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


def test_group_digits_mobile_and_other_lengths():
    assert group_digits("01012345678") == ["010", "1234", "5678"]
    assert group_digits("123456") == ["123", "456"]
    assert group_digits("12345") == ["123", "45"]
    assert group_digits("12") == ["12"]


def test_confirm_text_is_one_grouped_sentence():
    ar = confirm_text("01012345678", "ar-EG")
    assert ar == "قلت صفر واحد صفر، واحد اتنين تلاتة أربعة، خمسة ستة سبعة تمانية. صح كده؟"
    en = confirm_text("01012345678", "en-US")
    assert en == "You said zero one zero, one two three four, five six seven eight. Is that right?"


def test_confirm_only_on_questions():
    with pytest.raises(ScriptInvalid):
        validate_script(intake(steps=[{"key": "x", "say": "hi", "confirm": True}]))


def test_yes_keeps_the_number(engine):
    call = begin(engine)
    reply = say(engine, call, "01012345678")
    g = gather_of(reply)
    assert g["confirm_digits"] == "01012345678"
    assert g["prompt"] == confirm_text("01012345678", "ar-EG")
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


def test_a_question_mid_confirm_does_not_advance(engine):
    call = begin(engine)
    say(engine, call, "01012345678")
    before = engine.store.session_by_call(call)
    reply = say(engine, call, "هو الدوا غالي؟", {"kind": "off_script"})
    assert reply["verbs"][0]["key"] == "__offscript__"
    g = gather_of(reply)
    assert g["step"] == "mobile" and g["confirm_digits"] == "01012345678"
    after = engine.store.session_by_call(call)
    assert after["confirming"] == "01012345678"
    assert after["attempt"] == before["attempt"]


def test_readback_again_line_is_rendered():
    lines = main.voice_audio.lines(validate_script(intake()))
    keys = [l["key"] for l in lines if l["language"] == "ar-EG"]
    assert "__again__" in keys
    assert not any(k.startswith("__digit_") for k in keys)
    assert "__said__" not in keys


async def test_confirm_clip_speaks_one_cached_sentence(tmp_path, monkeypatch):
    audio = VoiceAudio(dataclasses.replace(
        main.settings, voice_tts_engine="say", voice_audio_dir=str(tmp_path / "audio"),
        voice_tts_cache=str(tmp_path / "tts"),
    ))
    clean = validate_script(intake())
    monkeypatch.setattr(speech, "synthesize", AsyncMock(return_value=b"m4a-bytes"))
    data_url, source = await audio.confirm_clip(
        tenant_id="t1", script=clean, language="ar-EG", persona=None, digits="0101"
    )
    assert source == "fallback" and data_url.startswith("data:audio/mp4;base64,")
    speech.synthesize.assert_awaited_once()
    spoken = speech.synthesize.await_args.args[0]
    assert spoken == confirm_text("0101", "ar-EG")
    # Second call is a cache hit — no new synthesize.
    await audio.confirm_clip(tenant_id="t1", script=clean, language="ar-EG", persona=None, digits="0101")
    assert speech.synthesize.await_count == 1


async def test_browser_call_reads_the_number_back(make_client, install_key, monkeypatch):
    heard = iter(["01012345678", "أيوه"])

    async def transcribe(audio, *, language, settings, digits_hint=False):
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
                assert t["clips"][0]["text"] == confirm_text("01012345678", "ar-EG")
                assert t["clips"][0]["audio"], "say engine: spoken whole, not silent"
        assert t["done"] is True
