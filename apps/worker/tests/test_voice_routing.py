"""One script per client: variables for the company, routes for the flow."""

from __future__ import annotations

import uuid

import pytest

from app.voice.engine import (
    MAX_CALLER_TURNS,
    ScriptInvalid,
    VoiceEngine,
    normalize_answer,
    validate_script,
)
from app.voice.store import VoiceStore


def pharma(**overrides):
    script = {
        "id": "psp-" + uuid.uuid4().hex[:6],
        "languages": ["ar-EG", "en-US"],
        "variables": {
            "company": {"ar-EG": "أكمي فارما", "en-US": "Acme Pharma"},
            "program": {"ar-EG": "برنامج أكمي كير", "en-US": "Acme Care"},
        },
        "steps": [
            {"key": "greeting", "next": "menu",
             "say": {"ar-EG": "أهلاً، معاك {{company}}. أهلاً بيك في {{program}}.",
                     "en-US": "Hello, this is {{company}}. Welcome to {{program}}."}},
            {"key": "menu", "gather": True, "next": "menu_again",
             "say": {"ar-EG": "إنت بتتصل علشان حالة جديدة ولا متابعة لحالة قديمة؟",
                     "en-US": "Are you calling about a new case or following up on an existing one?"},
             "routes": [
                 {"when": {"ar-EG": ["جديد", "جديدة", "أول مرة"], "en-US": ["new", "first time"]},
                  "next": "new_name", "value": "New"},
                 {"when": {"ar-EG": ["قديم", "متابعة", "متابعه"], "en-US": ["existing", "follow"]},
                  "next": "case_number", "value": "Follow-up"},
             ]},
            {"key": "menu_again", "next": "menu",
             "say": {"ar-EG": "معلش، ما سمعتش كويس.", "en-US": "Sorry, I did not catch that."}},
            {"key": "new_name", "gather": True, "next": "goodbye",
             "say": {"ar-EG": "ممكن اسمك بالكامل؟", "en-US": "May I have your full name?"}},
            {"key": "case_number", "gather": True, "next": "goodbye",
             "say": {"ar-EG": "إيه رقم الحالة؟", "en-US": "What is your case number?"}},
            {"key": "goodbye",
             "say": {"ar-EG": "شكراً لاتصالك بـ{{company}}.", "en-US": "Thank you for calling {{company}}."}},
        ],
        "commit": {"records": [{"sobject": "Case", "fields": {
            "Type": "{{menu}}", "Subject": "{{program}} call", "SuppliedName": "{{new_name}}",
            "Description": "{{transcript}}"}}]},
    }
    script.update(overrides)
    return script


@pytest.fixture()
def engine(tmp_path):
    return VoiceEngine(VoiceStore(str(tmp_path / "v.db")), public_base_url="https://api.test", ttl_days=7)


def start(engine, script, language):
    engine.store.upsert_script("t1", validate_script(script))
    call = "WB" + uuid.uuid4().hex
    reply = engine.start_call(tenant_id="t1", script_id=script["id"], call_sid=call,
                              from_label="web", language=language)
    return call, reply


def say(engine, call, step, text, attempt=None):
    """Answer the question the call is on now, echoing its turn like the page does."""
    session = engine.store.session_by_call(call)
    assert session["current_step"] == step
    return engine.on_gather(call_sid=call, step=step, attempt=attempt or session["attempt"],
                            speech=text, turn=session["turn"])


def spoken(reply):
    return [v.get("say") or v.get("gather", {}).get("prompt") for v in reply["verbs"] if not v.get("hangup")]


def test_variables_fill_every_language_and_the_crm():
    clean = validate_script(pharma())
    assert clean["steps"][0]["say"]["ar-EG"] == "أهلاً، معاك أكمي فارما. أهلاً بيك في برنامج أكمي كير."
    assert clean["steps"][0]["say"]["en-US"] == "Hello, this is Acme Pharma. Welcome to Acme Care."
    assert clean["commit"]["records"][0]["fields"]["Subject"] == "Acme Care call"  # CRM takes English
    assert clean["commit"]["records"][0]["fields"]["Type"] == "{{menu}}"  # answers stay templates


def test_a_plain_string_variable_works_in_both_languages():
    clean = validate_script(pharma(variables={"company": "Merck", "program": "Merck Cares"}))
    assert "Merck" in clean["steps"][0]["say"]["ar-EG"]


def test_a_misspelled_variable_is_a_publish_error():
    script = pharma()
    script["steps"][0]["say"]["en-US"] = "Hello, this is {{compnay}}."
    with pytest.raises(ScriptInvalid) as info:
        validate_script(script)
    assert "compnay" in str(info.value)


@pytest.mark.parametrize("bad", [
    lambda s: s["steps"][1]["routes"][0].update(next="nowhere"),
    lambda s: s["steps"][0].update(routes=[{"when": ["x"], "next": "menu"}]),  # announcements can't route
    lambda s: s["steps"][1]["routes"][0].update(when={"fr-FR": ["oui"]}),
    lambda s: s.update(variables={"menu": "clash with a step"}),
])
def test_bad_routes_and_variables_are_rejected(bad):
    script = pharma()
    bad(script)
    with pytest.raises(ScriptInvalid):
        validate_script(script)


def test_new_case_route(engine):
    call, reply = start(engine, pharma(), "ar-EG")
    assert spoken(reply)[0].startswith("أهلاً، معاك أكمي فارما")
    reply = say(engine, call, "menu", "لا دي حالة جديدة يا فندم")
    assert spoken(reply) == ["ممكن اسمك بالكامل؟"]
    reply = say(engine, call, "new_name", "أشرف رزق")
    session = engine.store.session_by_call(call)
    fields = session["commit_doc"]["records"][0]["fields"]
    assert session["status"] == "ready_to_commit"
    assert fields["Type"] == "New" and fields["SuppliedName"] == "أشرف رزق"


def test_follow_up_route_tolerates_arabic_spelling(engine):
    call, _ = start(engine, pharma(), "ar-EG")
    # whisper wrote ta marbuta as ha and added a hamza: still the follow-up route
    reply = say(engine, call, "menu", "عايز أعمل مُتابعه لحالة قديمة")
    assert spoken(reply) == ["إيه رقم الحالة؟"]
    say(engine, call, "case_number", "12345")
    fields = engine.store.session_by_call(call)["commit_doc"]["records"][0]["fields"]
    assert fields["Type"] == "Follow-up" and fields["SuppliedName"] == ""


def test_no_match_asks_again_then_routes(engine):
    call, _ = start(engine, pharma(), "en-US")
    reply = say(engine, call, "menu", "um, I am not sure")
    assert spoken(reply) == ["Sorry, I did not catch that.",
                             "Are you calling about a new case or following up on an existing one?"]
    reply = say(engine, call, "menu", "it's a new one")
    assert spoken(reply) == ["May I have your full name?"]


def test_an_endless_menu_loop_ends_the_call(engine):
    call, _ = start(engine, pharma(), "en-US")
    for _ in range(MAX_CALLER_TURNS):
        say(engine, call, "menu", "pizza")
    reply = say(engine, call, "menu", "pizza")
    assert reply["verbs"][-1] == {"hangup": True}
    assert engine.store.session_by_call(call)["status"] == "abandoned"


def test_normalize_answer():
    assert normalize_answer("أيوه!") == normalize_answer("ايوة") == " ايوه "
    assert normalize_answer("  New, PLEASE ") == " new please "
    assert normalize_answer("مُتابعة") == " متابعه "


def test_the_same_question_twice_is_not_a_retry(engine):
    """Looping back to a question is a new turn, not a replay of the cached first answer."""
    call, _ = start(engine, pharma(), "en-US")
    first = say(engine, call, "menu", "no idea")
    second = say(engine, call, "menu", "no idea again")
    assert first != second or engine.store.session_by_call(call)["turn"] == 3
    replay = engine.on_gather(call_sid=call, step="menu", attempt=1, speech="no idea", turn=1)
    assert replay == first, "a Twilio/page retry of turn 1 still replays"
