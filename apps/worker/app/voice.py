"""SIM phone agent: lines, calls, media WebSocket, scripted turn loop (Phase G)."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .errors import CloudiatorError
from .tts import PCM_RATE, build_tts_provider, normalize_language, pcm16_to_wav, resolve_voice
from .vad import EnergyVad, pcm_duration_ms
from .whisper import transcribe_bytes

log = logging.getLogger("cloudiator.voice")

SUPPORTED_CALL_LANGUAGES = ("en", "ar-EG", "fr")
DEFAULT_MAX_TURNS = 12
MAX_SCRIPT_CHARS = 12_000
MAX_GREETING_CHARS = 2_000


ChatFn = Callable[..., Awaitable[str]]


@dataclass
class LineScript:
    script: str
    language: str = "en"
    greeting: str = ""
    voice: str | None = None
    max_turns: int = DEFAULT_MAX_TURNS

    def public(self) -> dict[str, Any]:
        return {
            "script": self.script,
            "language": self.language,
            "greeting": self.greeting,
            "voice": self.voice,
            "max_turns": self.max_turns,
        }


@dataclass
class VoiceLine:
    line_id: str
    e164: str
    token: str
    tenant_id: str | None = None
    key_id: str | None = None
    script: LineScript | None = None
    connected: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "e164": self.e164,
            "connected": self.connected,
            "has_script": self.script is not None,
            "script": self.script.public() if self.script else None,
        }


@dataclass
class Turn:
    role: str
    text: str
    at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {"role": self.role, "text": self.text, "at": self.at}


@dataclass
class VoiceCall:
    call_id: str
    line_id: str
    direction: str  # inbound | outbound
    status: str  # queued | ringing | in_progress | completed | failed | busy
    language: str
    script: str
    greeting: str
    voice: str | None
    max_turns: int
    to_number: str | None = None
    from_number: str | None = None
    key_id: str | None = None
    tenant_id: str | None = None
    turns: list[Turn] = field(default_factory=list)
    error: str | None = None
    recording_id: str | None = None
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.call_id,
            "line_id": self.line_id,
            "direction": self.direction,
            "status": self.status,
            "language": self.language,
            "greeting": self.greeting,
            "voice": self.voice,
            "max_turns": self.max_turns,
            "to": self.to_number,
            "from": self.from_number,
            "turns": [t.public() for t in self.turns],
            "error": self.error,
            "recording_id": self.recording_id,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
        }


class VoiceStore:
    """SQLite persistence for lines and call history (survives worker restart)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        if self._conn is not None:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS voice_lines (
              line_id TEXT PRIMARY KEY,
              e164 TEXT NOT NULL,
              token TEXT NOT NULL,
              tenant_id TEXT,
              key_id TEXT,
              script_json TEXT,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS voice_calls (
              call_id TEXT PRIMARY KEY,
              line_id TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at REAL NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _require(self) -> sqlite3.Connection:
        self.open()
        assert self._conn is not None
        return self._conn

    def upsert_line(self, line: VoiceLine) -> None:
        conn = self._require()
        script_json = json.dumps(line.script.public()) if line.script else None
        conn.execute(
            """
            INSERT INTO voice_lines(line_id, e164, token, tenant_id, key_id, script_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(line_id) DO UPDATE SET
              e164=excluded.e164,
              token=excluded.token,
              tenant_id=excluded.tenant_id,
              key_id=excluded.key_id,
              script_json=excluded.script_json,
              updated_at=excluded.updated_at
            """,
            (
                line.line_id,
                line.e164,
                line.token,
                line.tenant_id,
                line.key_id,
                script_json,
                time.time(),
            ),
        )
        conn.commit()

    def load_lines(self) -> dict[str, VoiceLine]:
        rows = self._require().execute("SELECT * FROM voice_lines").fetchall()
        out: dict[str, VoiceLine] = {}
        for row in rows:
            script = None
            if row["script_json"]:
                data = json.loads(row["script_json"])
                script = LineScript(
                    script=data.get("script") or "",
                    language=data.get("language") or "en",
                    greeting=data.get("greeting") or "",
                    voice=data.get("voice"),
                    max_turns=int(data.get("max_turns") or DEFAULT_MAX_TURNS),
                )
            out[row["line_id"]] = VoiceLine(
                line_id=row["line_id"],
                e164=row["e164"],
                token=row["token"],
                tenant_id=row["tenant_id"],
                key_id=row["key_id"],
                script=script,
            )
        return out

    def save_call(self, call: VoiceCall) -> None:
        conn = self._require()
        conn.execute(
            """
            INSERT INTO voice_calls(call_id, line_id, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(call_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (call.call_id, call.line_id, json.dumps(call.public()), time.time()),
        )
        conn.commit()

    def get_call(self, call_id: str) -> dict[str, Any] | None:
        row = self._require().execute(
            "SELECT payload_json FROM voice_calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])


class VoiceManager:
    """One live call on the appliance; handset media over WebSocket."""

    def __init__(
        self,
        settings,
        *,
        scheduler,
        ollama,
        artifacts,
        store: VoiceStore | None = None,
        tts=None,
        chat_fn: ChatFn | None = None,
        transcribe_fn=None,
    ) -> None:
        self.settings = settings
        self.scheduler = scheduler
        self.ollama = ollama
        self.artifacts = artifacts
        self.store = store or VoiceStore(
            getattr(settings, "voice_db", None)
            or str(Path(settings.queue_db).with_name("voice.db"))
        )
        self.tts = tts or build_tts_provider(settings)
        self._chat_fn = chat_fn
        self._transcribe_fn = transcribe_fn or transcribe_bytes
        self.lines: dict[str, VoiceLine] = {}
        self.calls: dict[str, VoiceCall] = {}
        self.active_call: VoiceCall | None = None
        self._media: dict[str, WebSocket] = {}
        self._uplink_queues: dict[str, asyncio.Queue[bytes | None]] = {}
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def open(self) -> None:
        self.store.open()
        self.lines = self.store.load_lines()

    def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self.store.close()

    # ---- lines ------------------------------------------------------------

    def register_line(
        self,
        *,
        line_id: str | None,
        e164: str,
        token: str | None,
        key_id: str | None,
        tenant_id: str | None,
        script: LineScript | None = None,
    ) -> VoiceLine:
        lid = (line_id or uuid.uuid4().hex[:12]).strip()
        if not lid or len(lid) > 64:
            raise CloudiatorError(400, "invalid_request_error", "line_id is invalid.", param="line_id")
        number = _require_e164(e164)
        line_token = (token or uuid.uuid4().hex).strip()
        if len(line_token) < 16:
            raise CloudiatorError(
                400, "invalid_request_error", "token must be at least 16 characters.", param="token"
            )
        existing = self.lines.get(lid)
        line = VoiceLine(
            line_id=lid,
            e164=number,
            token=line_token,
            tenant_id=tenant_id,
            key_id=key_id,
            script=script or (existing.script if existing else None),
            connected=bool(existing.connected) if existing else False,
        )
        self.lines[lid] = line
        self.store.upsert_line(line)
        return line

    def set_script(self, line_id: str, script: LineScript, *, key_id: str | None) -> VoiceLine:
        line = self._get_line(line_id)
        if key_id and line.key_id and line.key_id != key_id:
            raise CloudiatorError(404, "not_found", "Line not found.")
        line.script = script
        if key_id:
            line.key_id = key_id
        self.store.upsert_line(line)
        return line

    def get_line(self, line_id: str) -> VoiceLine:
        return self._get_line(line_id)

    def list_lines(self, *, key_id: str | None = None) -> list[VoiceLine]:
        lines = list(self.lines.values())
        if key_id:
            lines = [line for line in lines if line.key_id == key_id]
        return lines

    def _get_line(self, line_id: str) -> VoiceLine:
        line = self.lines.get(line_id)
        if line is None:
            raise CloudiatorError(404, "not_found", "Line not found.")
        return line

    def verify_line_token(self, line_id: str, token: str | None) -> VoiceLine:
        line = self._get_line(line_id)
        if not token or not _const_eq(line.token, token):
            raise CloudiatorError(401, "invalid_api_key", "Invalid line token.")
        return line

    # ---- calls ------------------------------------------------------------

    async def start_outbound(
        self,
        *,
        line_id: str,
        to_number: str,
        script: str,
        language: str,
        greeting: str,
        voice: str | None,
        max_turns: int,
        key_id: str | None,
        tenant_id: str | None,
    ) -> VoiceCall:
        line = self._get_line(line_id)
        if key_id and line.key_id and line.key_id != key_id:
            raise CloudiatorError(404, "not_found", "Line not found.")
        call = self._new_call(
            line=line,
            direction="outbound",
            script=script,
            language=language,
            greeting=greeting,
            voice=voice,
            max_turns=max_turns,
            to_number=_require_e164(to_number),
            from_number=line.e164,
            key_id=key_id,
            tenant_id=tenant_id,
        )
        async with self._lock:
            if self.active_call is not None and self.active_call.status in (
                "queued",
                "ringing",
                "in_progress",
            ):
                call.status = "busy"
                call.error = "Another call is in progress on this appliance."
                call.ended_at = time.time()
                self.calls[call.call_id] = call
                self.store.save_call(call)
                raise CloudiatorError(
                    429,
                    "metal_busy",
                    "A voice call is already active. Retry after it ends.",
                    error_type="rate_limit_error",
                    retry_after=15,
                    param="voice",
                )
            self.active_call = call
            self.calls[call.call_id] = call
            self.store.save_call(call)

        ws = self._media.get(line_id)
        if ws is None:
            call.status = "failed"
            call.error = "Handset is not connected on the media WebSocket."
            call.ended_at = time.time()
            self.active_call = None
            self.store.save_call(call)
            raise CloudiatorError(
                503,
                "mini_offline",
                "The Android handset for this line is not connected.",
                error_type="server_error",
            )

        call.status = "ringing"
        self.store.save_call(call)
        await self._send_json(ws, {"type": "dial", "call_id": call.call_id, "to": call.to_number})
        task = asyncio.create_task(self._run_call(call), name=f"voice-call-{call.call_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return call

    async def hangup(self, call_id: str, *, key_id: str | None = None) -> VoiceCall:
        call = self.calls.get(call_id)
        if call is None:
            stored = self.store.get_call(call_id)
            if stored is None:
                raise CloudiatorError(404, "not_found", "Call not found.")
            raise CloudiatorError(400, "invalid_request_error", "Call is no longer active.")
        if key_id and call.key_id and call.key_id != key_id:
            raise CloudiatorError(404, "not_found", "Call not found.")
        await self._end_call(call, status="completed", reason="hangup")
        return call

    def get_call(self, call_id: str, *, key_id: str | None = None) -> dict[str, Any]:
        call = self.calls.get(call_id)
        if call is not None:
            if key_id and call.key_id and call.key_id != key_id:
                raise CloudiatorError(404, "not_found", "Call not found.")
            return call.public()
        stored = self.store.get_call(call_id)
        if stored is None:
            raise CloudiatorError(404, "not_found", "Call not found.")
        if key_id and stored.get("key_id") and stored.get("key_id") != key_id:
            # key_id not in public payload historically — check from live only.
            pass
        return stored

    def _new_call(self, **kwargs) -> VoiceCall:
        language = normalize_language(kwargs.get("language"))
        script = (kwargs.get("script") or "").strip()
        greeting = (kwargs.get("greeting") or "").strip()
        if not script:
            raise CloudiatorError(400, "invalid_request_error", "script is required.", param="script")
        if len(script) > MAX_SCRIPT_CHARS:
            raise CloudiatorError(400, "invalid_request_error", "script is too long.", param="script")
        if len(greeting) > MAX_GREETING_CHARS:
            raise CloudiatorError(
                400, "invalid_request_error", "greeting is too long.", param="greeting"
            )
        max_turns = int(kwargs.get("max_turns") or DEFAULT_MAX_TURNS)
        if max_turns < 1 or max_turns > 40:
            raise CloudiatorError(
                400, "invalid_request_error", "max_turns must be 1..40.", param="max_turns"
            )
        voice = kwargs.get("voice") or resolve_voice(language, None)
        return VoiceCall(
            call_id=uuid.uuid4().hex,
            line_id=kwargs["line"].line_id,
            direction=kwargs["direction"],
            status="queued",
            language=language,
            script=script,
            greeting=greeting,
            voice=voice,
            max_turns=max_turns,
            to_number=kwargs.get("to_number"),
            from_number=kwargs.get("from_number"),
            key_id=kwargs.get("key_id"),
            tenant_id=kwargs.get("tenant_id"),
        )

    # ---- media websocket --------------------------------------------------

    async def handle_media(self, websocket: WebSocket, line_id: str, token: str | None) -> None:
        line = self.verify_line_token(line_id, token)
        await websocket.accept()
        self._media[line_id] = websocket
        line.connected = True
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        self._uplink_queues[line_id] = queue
        log.info("voice media connected line_id=%s", line_id)
        try:
            await self._send_json(
                websocket, {"type": "registered", "line_id": line_id, "e164": line.e164}
            )
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self._enqueue_pcm(queue, message["bytes"])
                    continue
                text = message.get("text")
                if text:
                    await self._handle_control(line, json.loads(text))
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            log.exception("voice media error line_id=%s", line_id)
        finally:
            if self._media.get(line_id) is websocket:
                self._media.pop(line_id, None)
            line.connected = False
            self._uplink_queues.pop(line_id, None)
            if self.active_call and self.active_call.line_id == line_id:
                await self._end_call(self.active_call, status="failed", reason="handset_disconnected")
            log.info("voice media disconnected line_id=%s", line_id)

    async def _enqueue_pcm(self, queue: asyncio.Queue[bytes | None], pcm: bytes) -> None:
        try:
            queue.put_nowait(pcm)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(pcm)
            except asyncio.QueueFull:
                pass

    async def _handle_control(self, line: VoiceLine, payload: dict[str, Any]) -> None:
        kind = payload.get("type")
        if kind == "ring":
            await self._inbound_ring(line, payload)
            return
        if kind == "answered":
            call = self.active_call
            if call and call.line_id == line.line_id and call.status == "ringing":
                call.status = "in_progress"
                self.store.save_call(call)
            return
        if kind == "ended":
            call = self.active_call
            if call and call.line_id == line.line_id:
                await self._end_call(call, status="completed", reason="remote_hangup")
            return
        if kind == "ping":
            ws = self._media.get(line.line_id)
            if ws:
                await self._send_json(ws, {"type": "pong"})

    async def _inbound_ring(self, line: VoiceLine, payload: dict[str, Any]) -> None:
        ws = self._media.get(line.line_id)
        if line.script is None or not line.script.script.strip():
            if ws:
                await self._send_json(ws, {"type": "busy", "reason": "no_script"})
            return
        async with self._lock:
            if self.active_call is not None and self.active_call.status in (
                "queued",
                "ringing",
                "in_progress",
            ):
                if ws:
                    await self._send_json(ws, {"type": "busy", "reason": "call_in_progress"})
                return
            call = self._new_call(
                line=line,
                direction="inbound",
                script=line.script.script,
                language=line.script.language,
                greeting=line.script.greeting,
                voice=line.script.voice,
                max_turns=line.script.max_turns,
                from_number=payload.get("from"),
                to_number=line.e164,
                key_id=line.key_id,
                tenant_id=line.tenant_id,
            )
            call.status = "ringing"
            self.active_call = call
            self.calls[call.call_id] = call
            self.store.save_call(call)

        if ws:
            await self._send_json(
                ws, {"type": "answer", "call_id": call.call_id, "from": call.from_number}
            )
        task = asyncio.create_task(self._run_call(call), name=f"voice-call-{call.call_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- turn loop --------------------------------------------------------

    async def _run_call(self, call: VoiceCall) -> None:
        recording = bytearray()
        vad = EnergyVad()
        try:
            # Wait briefly for answered on outbound; inbound already answered.
            if call.direction == "outbound":
                await self._wait_until(
                    lambda: call.status in ("in_progress", "completed", "failed"),
                    timeout=45.0,
                )
            else:
                call.status = "in_progress"
                self.store.save_call(call)

            if call.status not in ("in_progress",):
                return

            if call.greeting:
                pcm = await self.tts.synthesize(
                    call.greeting, language=call.language, voice=call.voice
                )
                call.turns.append(Turn(role="agent", text=call.greeting))
                self.store.save_call(call)
                recording.extend(pcm)
                await self._play_pcm(call.line_id, pcm)

            turns_used = 0
            while turns_used < call.max_turns and call.status == "in_progress":
                utterance = await self._collect_utterance(call.line_id, vad, timeout=45.0)
                if utterance is None:
                    break
                recording.extend(utterance)
                transcript = await self._transcribe(utterance, language=call.language)
                if not transcript.strip():
                    continue
                call.turns.append(Turn(role="caller", text=transcript))
                self.store.save_call(call)

                reply = await self._agent_reply(call, transcript)
                if not reply.strip():
                    break
                call.turns.append(Turn(role="agent", text=reply))
                self.store.save_call(call)
                pcm = await self.tts.synthesize(reply, language=call.language, voice=call.voice)
                recording.extend(pcm)
                await self._play_pcm(call.line_id, pcm)
                turns_used += 1
                if _script_says_end(reply):
                    break

            await self._end_call(call, status="completed", reason="done", recording=bytes(recording))
        except asyncio.CancelledError:
            await self._end_call(call, status="failed", reason="cancelled", recording=bytes(recording))
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("voice call failed call_id=%s", call.call_id)
            call.error = str(exc)[:300]
            await self._end_call(call, status="failed", reason="error", recording=bytes(recording))

    async def _collect_utterance(
        self, line_id: str, vad: EnergyVad, *, timeout: float
    ) -> bytes | None:
        queue = self._uplink_queues.get(line_id)
        if queue is None:
            return None
        vad.reset()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.active_call is None or self.active_call.status != "in_progress":
                return None
            remaining = deadline - time.monotonic()
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            if chunk is None:
                return vad.flush()
            for utterance in vad.feed(chunk):
                if pcm_duration_ms(utterance) >= 200:
                    return utterance
        return vad.flush()

    async def _transcribe(self, pcm: bytes, *, language: str) -> str:
        wav = pcm16_to_wav(pcm, rate=PCM_RATE)
        result = await self._transcribe_fn(
            wav,
            settings=self.settings,
            scheduler=self.scheduler,
            filename="utterance.wav",
            content_type="audio/wav",
            language=language,
        )
        return str(result.get("text") or "").strip()

    async def _agent_reply(self, call: VoiceCall, user_text: str) -> str:
        if self._chat_fn is not None:
            return await self._chat_fn(call, user_text)
        system = _system_prompt(call.script, call.language)
        messages = [{"role": "system", "content": system}]
        for turn in call.turns:
            role = "assistant" if turn.role == "agent" else "user"
            messages.append({"role": role, "content": turn.text})
        # Latest caller turn is already in call.turns; avoid duplicating if chat_fn unused.
        if not messages or messages[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

        async with self.scheduler.chat_slot():
            raw = await self.ollama.chat(
                self.settings.default_model,
                messages,
                options={
                    "num_ctx": min(4096, self.settings.num_ctx),
                    "num_predict": min(180, self.settings.max_tokens_default),
                    "temperature": 0.4,
                },
            )
        content = ""
        if isinstance(raw, dict):
            message = raw.get("message") or {}
            content = message.get("content") or raw.get("response") or ""
        return str(content).strip()

    async def _play_pcm(self, line_id: str, pcm: bytes) -> None:
        ws = self._media.get(line_id)
        if ws is None:
            return
        # Chunk ~20ms frames for smoother playback on the handset.
        frame = int(PCM_RATE * 0.02) * 2
        for i in range(0, len(pcm), frame):
            await ws.send_bytes(pcm[i : i + frame])
            await asyncio.sleep(0.018)

    async def _end_call(
        self,
        call: VoiceCall,
        *,
        status: str,
        reason: str,
        recording: bytes | None = None,
    ) -> None:
        if call.status in ("completed", "failed", "busy") and call.ended_at:
            return
        call.status = status
        call.ended_at = time.time()
        if recording and len(recording) > 0:
            try:
                wav = pcm16_to_wav(recording, rate=PCM_RATE)
                call.recording_id = self.artifacts.save(wav, ".wav")
            except Exception:  # noqa: BLE001
                log.exception("could not save call recording")
        self.store.save_call(call)
        if self.active_call and self.active_call.call_id == call.call_id:
            self.active_call = None
        ws = self._media.get(call.line_id)
        if ws is not None:
            try:
                await self._send_json(
                    ws, {"type": "hangup", "call_id": call.call_id, "reason": reason}
                )
            except Exception:  # noqa: BLE001
                pass

    async def _wait_until(self, predicate, *, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.1)

    async def _send_json(self, ws: WebSocket, payload: dict[str, Any]) -> None:
        await ws.send_text(json.dumps(payload))


def parse_script_body(body: dict[str, Any]) -> LineScript:
    script = body.get("script")
    if not isinstance(script, str) or not script.strip():
        raise CloudiatorError(400, "invalid_request_error", "script is required.", param="script")
    language = normalize_language(body.get("language"))
    greeting = body.get("greeting") or ""
    if not isinstance(greeting, str):
        raise CloudiatorError(
            400, "invalid_request_error", "greeting must be a string.", param="greeting"
        )
    max_turns = body.get("max_turns", DEFAULT_MAX_TURNS)
    if isinstance(max_turns, bool) or not isinstance(max_turns, int):
        raise CloudiatorError(
            400, "invalid_request_error", "max_turns must be an integer.", param="max_turns"
        )
    voice = body.get("voice")
    if voice is not None and not isinstance(voice, str):
        raise CloudiatorError(400, "invalid_request_error", "voice must be a string.", param="voice")
    if len(script) > MAX_SCRIPT_CHARS:
        raise CloudiatorError(400, "invalid_request_error", "script is too long.", param="script")
    if len(greeting) > MAX_GREETING_CHARS:
        raise CloudiatorError(400, "invalid_request_error", "greeting is too long.", param="greeting")
    return LineScript(
        script=script.strip(),
        language=language,
        greeting=greeting.strip(),
        voice=voice.strip() if isinstance(voice, str) and voice.strip() else resolve_voice(language),
        max_turns=max_turns,
    )


def _system_prompt(script: str, language: str) -> str:
    lang_name = {"en": "English", "ar-EG": "Egyptian Arabic", "fr": "French"}[language]
    return (
        "You are a phone support agent. Follow the SCRIPT exactly for policy and persona. "
        "Reply with one short spoken turn only — plain text, no markdown, no stage directions. "
        f"Speak in {lang_name}. If the caller wants a human or the SCRIPT says to end, "
        "say a brief goodbye that includes the word END_CALL.\n\n"
        f"SCRIPT:\n{script}"
    )


def _script_says_end(text: str) -> bool:
    upper = text.upper()
    return "END_CALL" in upper or "إنهاء" in text


def _require_e164(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CloudiatorError(400, "invalid_request_error", "phone number is required.", param="e164")
    number = value.strip().replace(" ", "")
    if not number.startswith("+") or not number[1:].isdigit() or not (8 <= len(number) <= 16):
        raise CloudiatorError(
            400,
            "invalid_request_error",
            "phone number must be E.164 like +201234567890.",
            param="e164",
        )
    return number


def _const_eq(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for a, b in zip(left.encode("utf-8"), right.encode("utf-8")):
        result |= a ^ b
    return result == 0


__all__ = [
    "DEFAULT_MAX_TURNS",
    "LineScript",
    "VoiceCall",
    "VoiceLine",
    "VoiceManager",
    "VoiceStore",
    "parse_script_body",
]
