"""Browser call: the free, carrier-free front door to the same voice engine.

A tenant mints a call link for a script (Bearer + `voice`). Anyone with the
link opens a page on api.<domain>, presses Call, and talks: the page records
each answer in the browser, the Mini transcribes it locally (whisper.cpp, CPU)
and answers with locally synthesized audio (macOS `say`). The session, the
commit document, and the Salesforce ack are exactly the Twilio ones.

The link token is the only credential on the page. It can start calls for one
script and nothing else; it never carries an sk-cld- key.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..errors import CloudiatorError
from . import speech
from .engine import VoiceEngine
from .web_page import render_page

log = logging.getLogger("cloudiator.voice.web")

PER_IP_PER_MINUTE = 40


class _IpLimiter:
    """Turns per client IP per minute. The page makes one call per utterance."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, ip: str) -> None:
        now = time.monotonic()
        hits = self.hits[ip]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self.per_minute:
            raise CloudiatorError(
                429, "rate_limit_exceeded", "Too many call requests; wait a minute.", retry_after=30
            )
        hits.append(now)


def register_web_routes(app: FastAPI, *, engine: VoiceEngine, settings, require_key) -> None:
    store = engine.store
    limiter = _IpLimiter(PER_IP_PER_MINUTE)

    @app.post("/v1/voice/scripts/{script_id}/web-link")
    async def create_link(script_id: str, request: Request, key=Depends(require_key("voice"))) -> JSONResponse:
        if store.script_by_id(key.tenant_id, script_id) is None:
            raise CloudiatorError(404, "script_not_found", "No active script with that id.")
        token = store.create_web_link(key.tenant_id, script_id)
        request.state.usage.tool = "voice_web_link"
        return JSONResponse(
            content={
                "script_id": script_id,
                "url": f"{engine.base_url}/v1/voice/web/{token}",
                "note": "Shown once. Anyone with this URL can start a call on this script.",
            }
        )

    @app.post("/v1/voice/scripts/{script_id}/web-link/revoke")
    async def revoke_links(script_id: str, key=Depends(require_key("voice"))) -> JSONResponse:
        return JSONResponse(content={"revoked": store.revoke_web_links(key.tenant_id, script_id)})

    def link(request: Request, token: str) -> tuple[str, str]:
        found = store.web_link(token)
        if found is None:
            raise CloudiatorError(404, "link_not_found", "This call link is not valid.")
        tenant_id, script_id = found
        event = getattr(request.state, "usage", None)
        if event is not None:
            event.tenant_id = tenant_id
        return tenant_id, script_id

    @app.get("/v1/voice/web/{token}")
    async def call_page(token: str, request: Request) -> HTMLResponse:
        tenant_id, script_id = link(request, token)
        found = store.script_by_id(tenant_id, script_id)
        if found is None:
            raise CloudiatorError(404, "link_not_found", "This call link is not valid.")
        _version, script = found
        return HTMLResponse(
            render_page(title=script.get("display_name") or script_id, language=script.get("language")),
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "microphone=(self)",
            },
        )

    @app.post("/v1/voice/web/{token}/start")
    async def start(token: str, request: Request) -> JSONResponse:
        limiter.check(_client_ip(request))
        tenant_id, script_id = link(request, token)
        call_sid = "WB" + uuid.uuid4().hex
        request.state.usage.tool = "voice_web_start"
        reply = engine.start_call(
            tenant_id=tenant_id, script_id=script_id, call_sid=call_sid, from_label="web"
        )
        if reply is None:
            raise CloudiatorError(404, "link_not_found", "This call link is not valid.")
        return JSONResponse(content=await _turn(call_sid, reply, settings, heard=None))

    @app.post("/v1/voice/web/{token}/turn")
    async def turn(token: str, request: Request) -> JSONResponse:
        limiter.check(_client_ip(request))
        tenant_id, script_id = link(request, token)
        params = request.query_params
        call_sid = params.get("call_id") or ""
        session = store.session_by_call(call_sid) if call_sid.startswith("WB") else None
        if (
            session is None
            or session["tenant_id"] != tenant_id
            or session["to_number"] != f"web:{script_id}"
        ):
            raise CloudiatorError(404, "call_not_found", "Call not found.")
        try:
            attempt = int(params.get("attempt") or "1")
        except ValueError as exc:
            raise CloudiatorError(400, "invalid_request_error", "attempt must be an integer.") from exc
        step = params.get("step") or ""

        audio = await request.body()
        if len(audio) > settings.voice_web_max_audio_bytes:
            raise CloudiatorError(413, "request_too_large", "Audio is too long for one answer.")
        request.state.usage.tool = "voice_web_turn"
        # A retry of an answered turn replays without transcribing again.
        cached = store.reply_for(call_sid, step, attempt)
        if cached is not None:
            return JSONResponse(content=await _turn(call_sid, cached, settings, heard=None))
        try:
            heard = await speech.transcribe(
                audio, language=session["definition"].get("language"), settings=settings
            )
        except speech.SpeechUnavailable as exc:
            log.error("speech recognition unavailable: %s", exc)
            raise CloudiatorError(
                503, "speech_unavailable", "Speech recognition is not set up on this appliance.",
                error_type="server_error",
            ) from exc
        reply = engine.on_gather(call_sid=call_sid, step=step, attempt=attempt, speech=heard)
        return JSONResponse(content=await _turn(call_sid, reply, settings, heard=heard))


async def _turn(call_sid: str, reply: dict[str, Any], settings, *, heard: str | None) -> dict[str, Any]:
    """Reply → what the page plays: ordered clips, then listen or hang up."""
    voice_args = {
        "language": reply.get("language"),
        "local_voice": reply.get("local_voice"),
        "cache_dir": settings.voice_tts_cache,
    }
    clips = []
    listen = None
    done = False
    for verb in reply["verbs"]:
        text = verb.get("say") or (verb.get("gather") or {}).get("prompt")
        if text:
            clips.append({"text": text, "audio": await _audio(text, voice_args)})
        if "gather" in verb:
            g = verb["gather"]
            listen = {
                "step": g["step"],
                "attempt": g["attempt"],
                "timeout": g["timeout"],
                "speech_timeout": g["speech_timeout"],
            }
        if verb.get("hangup"):
            done = True
    return {"call_id": call_sid, "heard": heard, "clips": clips, "listen": listen, "done": done}


async def _audio(text: str, voice_args: dict[str, Any]) -> str | None:
    # No audio still leaves the text on screen; the call keeps working.
    try:
        return await speech.synthesize_data_url(text, **voice_args)
    except speech.SpeechUnavailable as exc:
        log.warning("tts unavailable: %s", exc)
        return None


def _client_ip(request: Request) -> str:
    # Behind cloudflared every request is from 127.0.0.1; Cloudflare sets this.
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
