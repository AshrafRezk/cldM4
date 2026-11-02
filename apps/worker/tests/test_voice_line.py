"""One call at a time; everyone else waits their turn, first come first served."""

from __future__ import annotations

import uuid

import pytest

from app.voice import speech
from app.voice.line import CallLine
from tests.voice_fixture import bilingual


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_fifo_positions_and_turns():
    clock = Clock()
    line = CallLine(capacity=1, clock=clock)
    assert line.can_start_now()
    line.started("WB1")
    a, b = line.join("link", "ar-EG"), line.join("link", "en-US")
    assert (line.position(a.id), line.position(b.id)) == (1, 2)
    assert line.take_turn(b.id) is None, "no jumping the line"
    assert line.take_turn(a.id) is None, "line still busy"
    line.ended("WB1")
    assert line.take_turn(a.id).language == "ar-EG"
    assert line.position(b.id) == 1
    line.started("WB2")
    assert not line.can_start_now()


def test_new_callers_never_skip_people_waiting():
    line = CallLine(capacity=1, clock=Clock())
    line.started("WB1")
    waiting = line.join("link", None)
    line.ended("WB1")
    assert line.free() and not line.can_start_now()
    # The route calls started() right after take_turn() with no await between,
    # so no other request can take the slot in between.
    assert line.take_turn(waiting.id) is not None
    line.started("WB2")
    assert not line.can_start_now()


def test_idle_calls_and_abandoned_tickets_expire():
    clock = Clock()
    line = CallLine(capacity=1, idle_seconds=90, wait_idle_seconds=30, clock=clock)
    line.started("WB1")
    gone = line.join("link", None)
    stays = line.join("link", None)
    clock.now += 20
    assert line.position(stays.id) == 2  # polling keeps a place
    clock.now += 15
    assert line.position(gone.id) is None, "stopped polling, lost their place"
    assert line.position(stays.id) == 1
    clock.now += 60
    line.position(stays.id)
    assert line.free(), "a page that went silent for 90 s frees the line"
    line.leave(stays.id)
    assert line.snapshot() == {"capacity": 1, "active": 0, "waiting": 0}


@pytest.fixture()
def fake_speech(monkeypatch):
    async def transcribe(audio, *, language, settings):
        return "Sara" if audio else ""

    async def synthesize(text, **kwargs):
        return b"fallback-audio"

    monkeypatch.setattr(speech, "transcribe", transcribe)
    monkeypatch.setattr(speech, "synthesize", synthesize)


async def answer(client, path, turn):
    q = {"call_id": turn["call_id"], "step": turn["listen"]["step"], "attempt": turn["listen"]["attempt"]}
    return (await client.post(f"{path}/turn", params=q, content=b"RIFF")).json()


async def test_second_caller_waits_then_connects(make_client, install_key, fake_speech):
    _r, headers = install_key(capabilities=["voice"])
    script = bilingual(id="q-" + uuid.uuid4().hex[:8])
    async with make_client(headers) as client:
        assert (await client.post("/v1/voice/scripts", json=script)).status_code == 200
        path = (await client.post(f"/v1/voice/scripts/{script['id']}/web-link")).json()["url"].removeprefix(
            "https://api.cloudiator.test"
        )
    async with make_client() as anon:
        first = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
        assert "call_id" in first and not first.get("queued")

        second = (await anon.post(f"{path}/start", params={"lang": "ar-EG"})).json()
        assert second["queued"] is True and second["position"] == 1
        assert second["clips"][0]["text"].startswith("شكراً لانتظارك")
        third = (await anon.post(f"{path}/start", params={"lang": "en-US"})).json()
        assert third["position"] == 2
        assert third["clips"][0]["text"].startswith("Thanks for holding")
        assert (await anon.get(f"{path}/line")).json() == {"capacity": 1, "active": 1, "waiting": 2}

        still = (await anon.post(f"{path}/wait", params={"ticket": second["ticket"]})).json()
        assert still == {**still, "queued": True, "position": 1, "clips": []}

        turn = first
        for _ in range(2):  # the bilingual fixture asks two questions
            turn = await answer(anon, path, turn)
        assert turn["done"] is True  # the first call finished and freed the line

        connected = (await anon.post(f"{path}/wait", params={"ticket": second["ticket"]})).json()
        assert "call_id" in connected and connected["language"] == "ar-EG"
        assert connected["clips"][1]["text"] == "ممكن تقولي اسمك بالكامل؟"
        assert (await anon.post(f"{path}/wait", params={"ticket": third["ticket"]})).json()["position"] == 1

        await anon.post(f"{path}/leave", params={"ticket": third["ticket"]})
        gone = await anon.post(f"{path}/wait", params={"ticket": third["ticket"]})
        assert gone.status_code == 404 and gone.json()["error"]["code"] == "ticket_expired"

        await anon.post(f"{path}/hangup", params={"call_id": connected["call_id"]})
        assert (await anon.get(f"{path}/line")).json()["active"] == 0

    async with make_client(headers) as client:
        sessions = {s["call_sid"]: s for s in (await client.get("/v1/voice/sessions")).json()["data"]}
    assert sessions[first["call_id"]]["status"] == "ready_to_commit"
    assert sessions[connected["call_id"]]["status"] == "abandoned"


async def test_a_ticket_only_works_on_its_own_link(make_client, install_key, fake_speech):
    _r, headers = install_key(capabilities=["voice"])
    paths = []
    async with make_client(headers) as client:
        for _ in range(2):
            script = bilingual(id="q-" + uuid.uuid4().hex[:8])
            await client.post("/v1/voice/scripts", json=script)
            made = await client.post(f"/v1/voice/scripts/{script['id']}/web-link")
            paths.append(made.json()["url"].removeprefix("https://api.cloudiator.test"))
    async with make_client() as anon:
        await anon.post(f"{paths[0]}/start")
        queued = (await anon.post(f"{paths[0]}/start")).json()
        stolen = await anon.post(f"{paths[1]}/wait", params={"ticket": queued["ticket"]})
    assert stolen.status_code == 404
