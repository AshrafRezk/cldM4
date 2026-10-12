"""SIM phone agent: scripts, busy-on-second-call, turn loop with fakes."""

from __future__ import annotations

import asyncio
import io
import wave

import pytest

from app.tts import FakeTtsProvider, pcm16_to_wav
from app.vad import EnergyVad
from app.voice import LineScript, VoiceManager, VoiceStore, parse_script_body
from app.errors import CloudiatorError


def _loud_pcm(ms: int = 500, sample_rate: int = 16000) -> bytes:
    import array
    import math

    n = int(sample_rate * ms / 1000)
    samples = array.array("h")
    for i in range(n):
        samples.append(int(12000 * math.sin(2 * math.pi * 440 * i / sample_rate)))
    return samples.tobytes()


def test_parse_script_body_requires_script():
    with pytest.raises(CloudiatorError):
        parse_script_body({"language": "en"})


def test_energy_vad_emits_utterance_after_silence():
    vad = EnergyVad()
    loud = _loud_pcm(400)
    quiet = b"\x00\x00" * (16000 // 1000 * 30)  # one 30ms silent frame worth of zeros... 
    # Feed enough silence frames after speech.
    out = []
    out.extend(vad.feed(loud))
    silence = b"\x00\x00" * (160 * 25)  # 25 frames of 10ms@16k... frame is 30ms=960 bytes
    # EnergyVad frame is 30ms = 960 bytes at 16k mono 16-bit
    frame = 16000 * 30 // 1000 * 2
    silence = b"\x00\x00" * (frame // 2 * 25)
    out.extend(vad.feed(silence))
    assert out, "expected at least one utterance"
    assert len(out[0]) > 1000


@pytest.fixture()
def voice_manager(tmp_path, settings):
    from app.scheduler import Scheduler
    from app.artifacts import ArtifactStore
    from unittest.mock import AsyncMock

    class FakeOllama:
        async def chat(self, model, messages, *, options, tools=None, response_format=None):
            return {"message": {"role": "assistant", "content": "Sure, I can help with that."}}

    store = VoiceStore(str(tmp_path / "voice.db"))
    artifacts = ArtifactStore(settings)
    scheduler = Scheduler(settings, FakeOllama())
    tts = FakeTtsProvider(pcm=b"\x00\x00" * 3200)

    async def fake_transcribe(data, **kwargs):
        return {"text": "I need help with my bill", "language": "en"}

    async def fake_chat(call, user_text):
        return f"Heard: {user_text}"

    mgr = VoiceManager(
        settings,
        scheduler=scheduler,
        ollama=FakeOllama(),
        artifacts=artifacts,
        store=store,
        tts=tts,
        chat_fn=fake_chat,
        transcribe_fn=fake_transcribe,
    )
    mgr.open()
    yield mgr, tts
    mgr.close()


def test_register_line_and_set_script(voice_manager):
    mgr, _tts = voice_manager
    line = mgr.register_line(
        line_id="desk-1",
        e164="+201000000001",
        token="line-token-at-least-16",
        key_id="key-1",
        tenant_id="t-1",
    )
    assert line.line_id == "desk-1"
    script = LineScript(
        script="You are a billing agent.",
        language="ar-EG",
        greeting="أهلاً بحضرتك",
        voice="ar-EG-SalmaNeural",
    )
    updated = mgr.set_script("desk-1", script, key_id="key-1")
    assert updated.script.greeting.startswith("أهلا")
    assert updated.public()["has_script"] is True


async def test_second_call_is_busy(voice_manager):
    mgr, _tts = voice_manager
    mgr.register_line(
        line_id="desk-1",
        e164="+201000000001",
        token="line-token-at-least-16",
        key_id="key-1",
        tenant_id="t-1",
        script=LineScript(script="Help callers.", language="en", greeting="Hello"),
    )

    class FakeWs:
        def __init__(self):
            self.sent = []

        async def send_text(self, text):
            self.sent.append(text)

        async def send_bytes(self, data):
            self.sent.append(data)

    ws = FakeWs()
    mgr._media["desk-1"] = ws
    mgr.lines["desk-1"].connected = True

    # Pretend a call is already active.
    from app.voice import VoiceCall

    active = VoiceCall(
        call_id="active1",
        line_id="desk-1",
        direction="inbound",
        status="in_progress",
        language="en",
        script="Help callers.",
        greeting="Hello",
        voice=None,
        max_turns=4,
    )
    mgr.active_call = active
    mgr.calls[active.call_id] = active

    with pytest.raises(CloudiatorError) as exc:
        await mgr.start_outbound(
            line_id="desk-1",
            to_number="+201000000099",
            script="Help callers.",
            language="en",
            greeting="Hello again",
            voice=None,
            max_turns=4,
            key_id="key-1",
            tenant_id="t-1",
        )
    assert exc.value.status_code == 429
    assert exc.value.code == "metal_busy"


async def test_greeting_is_spoken_verbatim(voice_manager):
    mgr, tts = voice_manager
    mgr.register_line(
        line_id="desk-1",
        e164="+201000000001",
        token="line-token-at-least-16",
        key_id="key-1",
        tenant_id="t-1",
    )

    class FakeWs:
        def __init__(self):
            self.texts = []
            self.bytes_chunks = []

        async def send_text(self, text):
            self.texts.append(text)

        async def send_bytes(self, data):
            self.bytes_chunks.append(data)

    ws = FakeWs()
    mgr._media["desk-1"] = ws
    mgr.lines["desk-1"].connected = True
    mgr._uplink_queues["desk-1"] = asyncio.Queue()

    call = await mgr.start_outbound(
        line_id="desk-1",
        to_number="+201000000099",
        script="You are a polite support agent for Acme.",
        language="en",
        greeting="Welcome to Acme support.",
        voice="en-US-JennyNeural",
        max_turns=1,
        key_id="key-1",
        tenant_id="t-1",
    )
    # Simulate handset answering.
    call.status = "in_progress"
    # Feed one utterance then end.
    q = mgr._uplink_queues["desk-1"]
    await q.put(_loud_pcm(500))
    await q.put(b"\x00\x00" * (960 * 25))

    # Let the call task run briefly.
    await asyncio.sleep(0.5)
    # Force end if still running.
    if mgr.active_call and mgr.active_call.call_id == call.call_id:
        await mgr.hangup(call.call_id, key_id="key-1")

    assert any(c["text"] == "Welcome to Acme support." for c in tts.calls)
    public = mgr.get_call(call.call_id, key_id="key-1")
    assert public["greeting"] == "Welcome to Acme support."
    assert public["turns"][0]["role"] == "agent"
    assert public["turns"][0]["text"] == "Welcome to Acme support."


async def test_http_create_line_and_script(make_client, install_key):
    _record, headers = install_key(capabilities=["voice_calls", "tts", "transcriptions", "chat"])
    async with make_client(headers) as client:
        created = await client.post(
            "/v1/voice/lines",
            json={
                "line_id": "sim-1",
                "e164": "+201111111111",
                "script": "Help with orders.",
                "language": "en",
                "greeting": "Thanks for calling.",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["line_id"] == "sim-1"
        assert "token" in body
        assert body["has_script"] is True

        updated = await client.put(
            "/v1/voice/lines/sim-1/script",
            json={
                "script": "Help with billing in Egyptian Arabic.",
                "language": "ar-EG",
                "greeting": "أهلاً",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["script"]["language"] == "ar-EG"


async def test_voice_calls_without_scope_is_403(make_client, install_key):
    _record, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/voice/lines",
            json={"e164": "+201111111111"},
        )
    assert response.status_code == 403


async def test_outbound_without_handset_is_503(make_client, install_key):
    _record, headers = install_key(capabilities=["voice_calls"])
    async with make_client(headers) as client:
        await client.post(
            "/v1/voice/lines",
            json={
                "line_id": "sim-2",
                "e164": "+201222222222",
                "script": "Help",
                "language": "en",
                "greeting": "Hi",
            },
        )
        response = await client.post(
            "/v1/voice/calls",
            json={
                "line_id": "sim-2",
                "to": "+201333333333",
                "script": "Help",
                "language": "en",
                "greeting": "Hi",
            },
        )
    assert response.status_code == 503
