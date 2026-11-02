"""Step machine without HTTP: validation, retries, idempotency, finish."""

from __future__ import annotations

import time
import uuid

import pytest

from app.voice.engine import ScriptInvalid, VoiceEngine, validate_script
from app.voice.store import NumberTaken, VoiceStore
from tests.voice_fixture import intake

TO = "+201000000001"


@pytest.fixture()
def engine(tmp_path):
    store = VoiceStore(str(tmp_path / "voice.db"))
    return VoiceEngine(store, public_base_url="https://api.test", ttl_days=7)


def publish(engine, tenant="t1", **overrides):
    script = validate_script(intake(**overrides))
    engine.store.upsert_script(tenant, script)
    return script


def inbound(engine, **kwargs):
    return engine.render_twiml(engine.on_inbound(**kwargs))


def gather(engine, **kwargs):
    return engine.render_twiml(engine.on_gather(**kwargs))


def sid():
    return "CA" + uuid.uuid4().hex


def test_inbound_speaks_greeting_then_gathers_name(engine):
    publish(engine)
    reply = inbound(engine, call_sid=sid(), from_number="+2011", to_number=TO)
    assert reply.index("<Say") < reply.index("<Gather")
    assert 'input="speech"' in reply
    assert 'language="ar-EG"' in reply
    assert "step=ask_name&amp;attempt=1" in reply
    assert "مرحباً" in reply


def test_full_call_reaches_ready_to_commit(engine):
    publish(engine)
    call = sid()
    inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    gather(engine, call_sid=call, step="ask_name", attempt=1, speech="سارة أحمد")
    gather(engine, call_sid=call, step="ask_reason", attempt=1, speech="أريد موعداً")
    reply = gather(engine, call_sid=call, step="ask_phone", attempt=1, speech="01012345678")
    assert reply.endswith("<Hangup/></Response>")
    assert "شكراً" in reply

    session = engine.store.session_by_call(call)
    assert session["status"] == "ready_to_commit"
    lead, task = session["commit_doc"]["records"]
    assert lead["fields"]["LastName"] == "سارة أحمد"
    assert lead["fields"]["Phone"] == "01012345678"
    assert lead["fields"]["Description"].startswith("أريد موعداً\n\n---\nAgent: مرحباً")
    assert task["fields"]["WhoId"] == "{{Lead.Id}}"
    assert task["after"] == ["Lead"]
    roles = [t["role"] for t in session["turns"]]
    assert roles == ["agent", "agent", "caller", "agent", "caller", "agent", "caller", "agent"]


def test_twilio_retry_returns_same_twiml_and_one_answer(engine):
    publish(engine)
    call = sid()
    inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    first = gather(engine, call_sid=call, step="ask_name", attempt=1, speech="Sara")
    again = gather(engine, call_sid=call, step="ask_name", attempt=1, speech="Sara")
    assert first == again
    session = engine.store.session_by_call(call)
    assert [t["text"] for t in session["turns"] if t["role"] == "caller"] == ["Sara"]
    assert session["current_step"] == "ask_reason"


def test_inbound_retry_does_not_open_a_second_session(engine):
    publish(engine)
    call = sid()
    first = inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    assert inbound(engine, call_sid=call, from_number="+2011", to_number=TO) == first


def test_silence_replays_then_continues_empty(engine):
    publish(engine)
    call = sid()
    inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    replay = gather(engine, call_sid=call, step="ask_name", attempt=1, speech="")
    assert "step=ask_name&amp;attempt=2" in replay
    moved_on = gather(engine, call_sid=call, step="ask_name", attempt=2, speech="  ")
    assert "step=ask_reason&amp;attempt=1" in moved_on
    assert engine.store.session_by_call(call)["answers"]["ask_name"] == ""


def test_on_fail_hangup_abandons(engine):
    script = intake()
    script["steps"][1]["on_fail"] = "hangup"
    script["steps"][1]["max_attempts"] = 1
    engine.store.upsert_script("t1", validate_script(script))
    call = sid()
    inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    reply = gather(engine, call_sid=call, step="ask_name", attempt=1, speech="")
    assert "<Hangup/>" in reply and "عذراً" in reply
    assert engine.store.session_by_call(call)["status"] == "abandoned"


def test_out_of_order_gather_hangs_up_without_answer(engine):
    publish(engine)
    call = sid()
    inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    reply = gather(engine, call_sid=call, step="ask_phone", attempt=1, speech="x")
    assert reply.endswith("<Response><Hangup/></Response>")
    assert engine.store.session_by_call(call)["answers"] == {}


def test_unrouted_number_hangs_up(engine):
    reply = inbound(engine, call_sid=sid(), from_number="+2011", to_number="+19995550000")
    assert "<Hangup/>" in reply
    assert "<Gather" not in reply


def test_caller_text_is_xml_escaped(engine):
    publish(engine)
    call = sid()
    inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    script = intake(id="echo", inbound_numbers=["+201000000002"])
    script["steps"][4]["say"] = "<Play>http://evil</Play> & bye"
    engine.store.upsert_script("t1", validate_script(script))
    call2 = sid()
    inbound(engine, call_sid=call2, from_number="+2011", to_number="+201000000002")
    for step in ("ask_name", "ask_reason"):
        gather(engine, call_sid=call2, step=step, attempt=1, speech="x")
    reply = gather(engine, call_sid=call2, step="ask_phone", attempt=1, speech="y")
    assert "<Play>" not in reply
    assert "&lt;Play&gt;" in reply and "&amp; bye" in reply


def test_number_belongs_to_one_tenant(engine):
    publish(engine, tenant="t1")
    with pytest.raises(NumberTaken):
        publish(engine, tenant="t2")


def test_republish_bumps_version_and_moves_numbers(engine):
    publish(engine)
    result = engine.store.upsert_script("t1", validate_script(intake(inbound_numbers=["+201000000009"])))
    assert result["version"] == 2
    assert engine.store.script_for_number(TO) is None
    assert engine.store.script_for_number("+201000000009")[0] == "t1"


def test_purge_drops_old_sessions(engine):
    publish(engine)
    call = sid()
    inbound(engine, call_sid=call, from_number="+2011", to_number=TO)
    session = engine.store.session_by_call(call)
    engine.store.update_session(session["id"], acked_at=time.time() - 8 * 86400)
    assert engine.store.purge_expired(7) == 1
    assert engine.store.session_by_call(call) is None
    assert engine.store.reply_for(call, "__inbound__", 0) is None


def test_reply_is_channel_neutral(engine):
    publish(engine)
    reply = engine.on_inbound(call_sid=sid(), from_number="+2011", to_number=TO)
    assert reply["language"] == "ar-EG"
    assert [next(iter(v)) for v in reply["verbs"]] == ["say", "gather"]
    assert reply["verbs"][1]["gather"]["step"] == "ask_name"


def test_start_call_by_script_id(engine):
    publish(engine)
    call = sid()
    reply = engine.start_call(tenant_id="t1", script_id="intake-ar", call_sid=call, from_label="web")
    assert reply["verbs"][-1]["gather"]["step"] == "ask_name"
    assert engine.start_call(tenant_id="t1", script_id="intake-ar", call_sid=call, from_label="web") == reply
    assert engine.start_call(tenant_id="t2", script_id="intake-ar", call_sid=sid(), from_label="web") is None


@pytest.mark.parametrize(
    "mutate, param",
    [
        (lambda s: s.update(id="bad id"), "id"),
        (lambda s: s.update(steps=[]), "steps"),
        (lambda s: s["steps"][0].update(next="nowhere"), "steps"),
        # greeting -> goodbye -> greeting: announcements only, would talk forever
        (lambda s: (s["steps"][4].update(next="greeting"), s["steps"][0].update(next="goodbye")), "steps"),
        (lambda s: s["steps"][1].update(key="transcript"), "steps[1].key"),
        (lambda s: s["steps"][1].update(max_attempts=9), "steps[1].max_attempts"),
        (lambda s: s.update(inbound_numbers=["0100"]), "inbound_numbers"),
        (lambda s: s["commit"]["records"][1].update(after=["Account"]), "commit.records[1].after"),
        (lambda s: s["commit"]["records"][0].update(sobject="Lead; DROP"), "commit.records[0].sobject"),
    ],
)
def test_invalid_scripts_are_rejected(mutate, param):
    script = intake()
    mutate(script)
    with pytest.raises(ScriptInvalid) as info:
        validate_script(script)
    assert info.value.param == param
