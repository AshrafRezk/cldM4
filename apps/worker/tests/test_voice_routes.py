"""HTTP proof for docs/claude-code-handoff.md §7: signed Twilio webhooks, tenant
isolation, ack, and a composition-free Salesforce OpenAPI."""

from __future__ import annotations

import json
import uuid
from urllib.parse import urlencode

import pytest

from app import main
from app.voice.engine import validate_script
from app.voice.twilio_sig import compute_signature
from tests.voice_fixture import intake

TOKEN = "test-twilio-auth-token"
BASE = "https://api.cloudiator.test"


def unique_script():
    """The voice DB lives for the whole session, so each test owns its number."""
    number = "+2010" + str(uuid.uuid4().int)[:8]
    return intake(id="intake-" + uuid.uuid4().hex[:8], inbound_numbers=[number]), number


async def twilio(client, path, form, *, signature=None):
    url = BASE + path
    sig = signature if signature is not None else compute_signature(TOKEN, url, form.items())
    return await client.post(
        path,
        content=urlencode(form),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": sig,
        },
    )


def gather_path(step, attempt=1):
    return "/v1/voice/twilio/gather?" + urlencode({"step": step, "attempt": attempt})


@pytest.fixture()
def voice_key(install_key):
    return install_key(capabilities=["chat", "voice"])


async def test_publish_call_commit_ack(make_client, voice_key):
    record, headers = voice_key
    script, number = unique_script()
    call_sid = "CA" + uuid.uuid4().hex
    call = {"CallSid": call_sid, "From": "+201112223333", "To": number}

    async with make_client(headers) as client:
        published = await client.post(
            "/v1/voice/scripts", json={"definition": json.dumps(script, ensure_ascii=False)}
        )
        assert published.status_code == 200, published.text
        assert published.json()["version"] == 1

        listed = (await client.get("/v1/voice/scripts")).json()["data"]
        assert script["id"] in [row["id"] for row in listed]

        inbound = await twilio(client, "/v1/voice/twilio/inbound", call)
        assert inbound.status_code == 200
        assert inbound.headers["content-type"].startswith("application/xml")
        assert "<Say" in inbound.text and "<Gather" in inbound.text

        for step, speech in (
            ("ask_name", "سارة أحمد"),
            ("ask_reason", "حجز موعد"),
            ("ask_phone", "01012345678"),
        ):
            reply = await twilio(client, gather_path(step), {**call, "SpeechResult": speech})
            assert reply.status_code == 200, reply.text

        ready = (await client.get("/v1/voice/sessions", params={"status": "ready_to_commit"})).json()
        session = next(s for s in ready["data"] if s["call_sid"] == call_sid)
        assert session["status"] == "ready_to_commit"
        assert session["commit"]["records"][0]["fields"]["LastName"] == "سارة أحمد"
        assert json.loads(session["commit_json"]) == session["commit"]
        assert "Caller: حجز موعد" in session["transcript"]

        ack = await client.post(
            f"/v1/voice/sessions/{session['id']}/ack",
            json={"records": [{"sobject": "Lead", "id": "00Q000000000001AAA"},
                              {"sobject": "Task", "id": "00T000000000001"}]},
        )
        assert ack.status_code == 200, ack.text
        assert ack.json()["status"] == "committed"
        assert ack.json()["committed_ids"]["Lead"] == "00Q000000000001AAA"

        again = await client.post(
            f"/v1/voice/sessions/{session['id']}/ack",
            json={"record_ids": {"Lead": "00Q000000000001AAA", "Task": "00T000000000001"}},
        )
        assert again.status_code == 200
        different = await client.post(
            f"/v1/voice/sessions/{session['id']}/ack",
            json={"record_ids": {"Lead": "00Q000000000002AAA"}},
        )
        assert different.status_code == 409


async def test_bad_signature_is_403_and_never_twiml(make_client):
    script, number = unique_script()
    main.voice.store.upsert_script("tenant-x", validate_script(script))
    async with make_client() as client:
        response = await twilio(
            client,
            "/v1/voice/twilio/inbound",
            {"CallSid": "CAbad", "From": "+2011", "To": number},
            signature="AAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        )
        missing = await client.post(
            "/v1/voice/twilio/inbound",
            content="CallSid=CAbad",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    for r in (response, missing):
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "invalid_signature"
        assert "<Response" not in r.text


async def test_signature_covers_the_query_string(make_client):
    """A valid signature for one step cannot be replayed onto another."""
    form = {"CallSid": "CAq", "SpeechResult": "x"}
    sig = compute_signature(TOKEN, BASE + gather_path("ask_name"), form.items())
    async with make_client() as client:
        response = await twilio(client, gather_path("ask_phone"), form, signature=sig)
    assert response.status_code == 403


async def test_tenant_b_cannot_see_tenant_a_sessions(make_client, install_key):
    _a, headers_a = install_key(capabilities=["voice"])
    _b, headers_b = install_key(capabilities=["voice"])
    script, number = unique_script()
    call_sid = "CA" + uuid.uuid4().hex
    async with make_client(headers_a) as client:
        assert (await client.post("/v1/voice/scripts", json=script)).status_code == 200
        await twilio(client, "/v1/voice/twilio/inbound", {"CallSid": call_sid, "From": "+2011", "To": number})
        mine = (await client.get("/v1/voice/sessions")).json()["data"]
        session_id = next(s["id"] for s in mine if s["call_sid"] == call_sid)

    async with make_client(headers_b) as client:
        assert (await client.get(f"/v1/voice/sessions/{session_id}")).status_code == 404
        theirs = (await client.get("/v1/voice/sessions")).json()["data"]
        assert session_id not in [s["id"] for s in theirs]
        ack = await client.post(
            f"/v1/voice/sessions/{session_id}/ack", json={"record_ids": {"Lead": "00Q000000000001"}}
        )
        assert ack.status_code == 404
        stolen = await client.post("/v1/voice/scripts", json={**script, "id": "steal"})
        assert stolen.status_code == 409


async def test_voice_routes_need_the_voice_scope(make_client, install_key):
    _record, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.get("/v1/voice/sessions")
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "scope_denied"
    assert "set-capabilities" in body["message"]
    assert "--add voice" in body["message"]


async def test_bad_script_is_400_with_param(make_client, voice_key):
    _record, headers = voice_key
    script, _ = unique_script()
    script["steps"][0]["next"] = "missing"
    async with make_client(headers) as client:
        response = await client.post("/v1/voice/scripts", json=script)
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "steps"


async def test_ack_before_ready_is_409(make_client, voice_key):
    _record, headers = voice_key
    script, number = unique_script()
    call_sid = "CA" + uuid.uuid4().hex
    async with make_client(headers) as client:
        await client.post("/v1/voice/scripts", json=script)
        await twilio(client, "/v1/voice/twilio/inbound", {"CallSid": call_sid, "From": "+2011", "To": number})
        session = next(
            s for s in (await client.get("/v1/voice/sessions")).json()["data"] if s["call_sid"] == call_sid
        )
        response = await client.post(
            f"/v1/voice/sessions/{session['id']}/ack", json={"record_ids": {"Lead": "00Q000000000001"}}
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_ready"


async def test_outbound_is_a_501_stub(make_client, voice_key):
    _record, headers = voice_key
    async with make_client(headers) as client:
        response = await client.post("/v1/voice/calls", json={})
    assert response.status_code == 501


async def test_salesforce_oas_has_voice_and_no_composition(make_client, install_key):
    from app.openapi_filter import load_generator

    preset = load_generator().load_scopes()["presets"]["salesforce_engineer"]["capabilities"]
    assert "voice" in preset
    _record, headers = install_key(capabilities=preset)
    async with make_client(headers) as client:
        response = await client.get("/v1/openapi.json", params={"target": "salesforce"})
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc["openapi"] == "3.0.3"
    assert "/v1/voice/sessions/{id}/ack" in doc["paths"]
    assert not [p for p in doc["paths"] if "twilio" in p]
    assert load_generator().composition_keys(doc) == []
