"""Callers ask things mid-script. The agent answers from pre-written FAQs (or
notes the question), then goes straight back to the question it asked."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app import main
from app.voice import speech
from app.voice.assistant import VoiceAssistant
from app.voice.engine import ScriptInvalid, VoiceEngine, looks_like_question, validate_script
from app.voice.store import VoiceStore


def psp(**overrides):
    script = {
        "id": "faq-" + uuid.uuid4().hex[:6],
        "languages": ["ar-EG", "en-US"],
        "variables": {"company": "Acme"},
        "steps": [
            {"key": "ask_name", "gather": True, "next": "ask_phone",
             "say": {"ar-EG": "ممكن اسمك بالكامل؟", "en-US": "May I have your full name?"},
             "routes": [{"when": ["new"], "next": "ask_phone"}]},
            {"key": "ask_phone", "gather": True, "next": "goodbye",
             "say": {"ar-EG": "إيه رقم موبايلك؟", "en-US": "What is your mobile number?"}},
            {"key": "goodbye", "say": {"ar-EG": "شكراً.", "en-US": "Thank you."}},
        ],
        "faq": [
            {"key": "food", "when": {"ar-EG": ["قبل الاكل", "بعد الاكل"], "en-US": ["food", "meal"]},
             "say": {"ar-EG": "الدوا ده بيتاخد بعد الأكل.", "en-US": "Take it after a meal."}},
            {"key": "hours", "when": ["open", "hours", "مواعيد"],
             "say": {"ar-EG": "{{company}} شغالة من ٩ لـ ٥.", "en-US": "{{company}} is open nine to five."}},
        ],
        "commit": {"records": [{"sobject": "Case", "fields": {
            "SuppliedName": "{{ask_name}}", "Description": "Questions:\n{{questions}}"}}]},
    }
    script.update(overrides)
    return script


@pytest.fixture()
def engine(tmp_path):
    return VoiceEngine(VoiceStore(str(tmp_path / "v.db")), public_base_url="https://api.test", ttl_days=7)


def begin(engine, script, language="en-US"):
    engine.store.upsert_script("t1", validate_script(script))
    call = "WB" + uuid.uuid4().hex
    engine.start_call(tenant_id="t1", script_id=script["id"], call_sid=call, from_label="web", language=language)
    return call


def answer(engine, call, text, intent=None):
    s = engine.store.session_by_call(call)
    return engine.on_gather(call_sid=call, step=s["current_step"], attempt=s["attempt"],
                            speech=text, turn=s["turn"], intent=intent)


def test_faq_validates_and_fills_variables():
    clean = validate_script(psp())
    assert clean["faq"][1]["say"]["en-US"] == "Acme is open nine to five."
    assert " قبل الاكل " in " ".join(clean["faq"][0]["when"]["ar-EG"]) + " "
    with pytest.raises(ScriptInvalid):
        validate_script(psp(faq=[{"key": "ask_name", "when": ["x"], "say": "y"}]))  # clashes with a step
    with pytest.raises(ScriptInvalid):
        validate_script(psp(faq=[{"key": "k", "when": [], "say": "y"}]))


@pytest.mark.parametrize("text, lang, expected", [
    ("هو الدوا ده بيتاخد قبل الأكل", "ar-EG", True),
    ("عندي سؤال عن المواعيد", "ar-EG", True),
    ("أشرف رزق", "ar-EG", False),
    ("Sarah?", "en-US", False),
    ("What time are you open?", "en-US", True),
    ("can I take it with food", "en-US", True),
    ("01012345678", "en-US", False),
])
def test_question_detection(text, lang, expected):
    assert looks_like_question(text, lang) is expected


def test_an_faq_answer_then_back_to_the_same_question(engine):
    call = begin(engine, psp())
    before = engine.store.session_by_call(call)
    reply = answer(engine, call, "Can I take it with food?", {"kind": "faq", "key": "food"})
    spoken = [v.get("say") or v["gather"]["prompt"] for v in reply["verbs"]]
    assert spoken == ["Take it after a meal.", "Now, back to my question.", "May I have your full name?"]
    keys = [v.get("key") for v in reply["verbs"][:2]]
    assert keys == ["__faq_food", "__back__"]
    after = engine.store.session_by_call(call)
    assert after["current_step"] == "ask_name" and after["attempt"] == before["attempt"]
    assert after["turn"] == before["turn"] + 1
    answer(engine, call, "Sara Ahmed")
    answer(engine, call, "0101")
    fields = engine.store.session_by_call(call)["commit_doc"]["records"][0]["fields"]
    assert fields["SuppliedName"] == "Sara Ahmed"
    assert fields["Description"] == "Questions:\nCan I take it with food"


def test_an_unknown_question_is_noted_not_answered(engine):
    call = begin(engine, psp(), "ar-EG")
    reply = answer(engine, call, "هو ينفع آخد الدوا مع القهوة؟", {"kind": "off_script"})
    assert reply["verbs"][0]["key"] == "__offscript__"
    assert "سجلته" in reply["verbs"][0]["say"]
    assert reply["verbs"][-1]["gather"]["step"] == "ask_name"


class FakeOllama:
    def __init__(self, content=None, delay=0.0):
        self.content, self.delay, self.calls = content, delay, 0

    async def chat(self, model, messages, *, options, response_format=None, tools=None, think=None):
        self.calls += 1
        assert think is False, "a JSON routing decision must not spend tokens thinking"
        await asyncio.sleep(self.delay)
        assert response_format == "json_object" and "Never write an answer" in messages[0]["content"]
        return {"message": {"content": self.content}}


def assistant(ollama=None, **settings):
    import dataclasses

    return VoiceAssistant(dataclasses.replace(main.settings, **settings), ollama=ollama)


async def test_keywords_first_then_the_model_then_noted():
    clean = validate_script(psp())
    step = clean["steps"][1]
    model = FakeOllama(json.dumps({"faq": "hours"}))
    a = assistant(model, voice_llm_faq=True, voice_llm_timeout_seconds=2)
    assert await a.intent(clean, step, "is it ok after a meal?", "en-US") == {"kind": "faq", "key": "food"}
    assert model.calls == 0, "keywords matched, no model call"
    assert await a.intent(clean, step, "when do your nurses start in the morning?", "en-US") == {"kind": "faq", "key": "hours"}
    assert model.calls == 1
    assert await a.intent(clean, step, "01012345678", "en-US") is None, "an answer is an answer"

    made_up = assistant(FakeOllama(json.dumps({"faq": "not_a_key"})), voice_llm_faq=True)
    assert await made_up.intent(clean, step, "what is the weather like?", "en-US") == {"kind": "off_script"}
    slow = assistant(FakeOllama(json.dumps({"faq": "hours"}), delay=1.0), voice_llm_faq=True, voice_llm_timeout_seconds=0.1)
    assert await slow.intent(clean, step, "when do you close?", "en-US") == {"kind": "off_script"}
    off = assistant(FakeOllama(json.dumps({"faq": "hours"})), voice_llm_faq=False)
    assert await off.intent(clean, step, "when do you close?", "en-US") == {"kind": "off_script"}


async def test_a_route_keyword_is_an_answer_even_as_a_question():
    clean = validate_script(psp())
    a = assistant(None)
    assert await a.intent(clean, clean["steps"][0], "is it new? yes it is new", "en-US") is None


def test_faq_lines_are_rendered_like_any_other():
    lines = main.voice_audio.lines(validate_script(psp()))
    keys = {l["key"] for l in lines if l["language"] == "en-US"}
    assert {"__faq_food", "__faq_hours", "__back__", "__offscript__"} <= keys


async def test_browser_call_answers_a_question_then_re_asks(make_client, install_key, monkeypatch):
    heard = iter(["Can I take this with food?", "Sara Ahmed"])

    async def transcribe(audio, *, language, settings):
        return next(heard)

    async def synthesize(text, **kwargs):
        return b"fallback-audio"

    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "synthesize", synthesize)
    _r, headers = install_key(capabilities=["voice"])
    script = psp()
    async with make_client(headers) as client:
        await client.post("/v1/voice/scripts", json=script)
        path = (await client.post(f"/v1/voice/scripts/{script['id']}/web-link")).json()["url"].removeprefix(
            "https://api.cloudiator.test")
    async with make_client() as anon:
        t = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
        q = {"call_id": t["call_id"], "step": t["listen"]["step"], "attempt": t["listen"]["attempt"], "turn": t["listen"]["turn"]}
        t = (await anon.post(f"{path}/turn", params=q, content=b"RIFF")).json()
        assert [c["text"] for c in t["clips"]] == ["Take it after a meal.", "Now, back to my question.", "May I have your full name?"]
        assert t["listen"]["step"] == "ask_name"
        q = {"call_id": t["call_id"], "step": "ask_name", "attempt": t["listen"]["attempt"], "turn": t["listen"]["turn"]}
        t = (await anon.post(f"{path}/turn", params=q, content=b"RIFF")).json()
        assert t["clips"][0]["text"] == "What is your mobile number?"
