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
from .engine import ScriptInvalid, VoiceEngine, hold_text, languages_of, session_language
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


def register_web_routes(app: FastAPI, *, engine: VoiceEngine, audio, line, settings, require_key) -> None:
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
            render_page(title=script.get("display_name") or script_id, languages=languages_of(script)),
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "microphone=(self)",
            },
        )

    def begin(tenant_id: str, script_id: str, language: str | None) -> tuple[str, dict[str, Any]]:
        call_sid = "WB" + uuid.uuid4().hex
        try:
            reply = engine.start_call(
                tenant_id=tenant_id, script_id=script_id, call_sid=call_sid,
                from_label="web", language=language,
            )
        except ScriptInvalid as exc:
            raise CloudiatorError(400, "invalid_request_error", str(exc), param="lang") from exc
        if reply is None:
            raise CloudiatorError(404, "link_not_found", "This call link is not valid.")
        line.started(call_sid)
        return call_sid, reply

    async def hold(tenant_id: str, script_id: str, ticket, position: int, with_audio: bool) -> dict[str, Any]:
        found = store.script_by_id(tenant_id, script_id)
        script = found[1] if found else {"id": script_id}
        language = ticket.language or (script.get("language") or "en-US")
        clips = []
        if with_audio and found:
            text = hold_text(script, language)
            data_url, source = await audio.clip(
                tenant_id=tenant_id, script=script, key="__hold__", language=language, text=text
            )
            clips.append({"text": text, "audio": data_url, "source": source})
        return {"queued": True, "ticket": ticket.id, "position": position, "language": language,
                "clips": clips, "poll_seconds": 3}

    @app.post("/v1/voice/web/{token}/start")
    async def start(token: str, request: Request) -> JSONResponse:
        """Connect now if the line is free and nobody is waiting; otherwise join the line."""
        limiter.check(_client_ip(request))
        tenant_id, script_id = link(request, token)
        language = request.query_params.get("lang") or None
        found = store.script_by_id(tenant_id, script_id)
        if found is None:
            raise CloudiatorError(404, "link_not_found", "This call link is not valid.")
        if language is not None and language not in languages_of(found[1]):
            raise CloudiatorError(400, "invalid_request_error", f"This script does not speak {language}.", param="lang")
        request.state.usage.tool = "voice_web_start"
        if line.can_start_now():
            call_sid, reply = begin(tenant_id, script_id, language)
            return JSONResponse(content=await _turn(audio, tenant_id, call_sid, reply, store, heard=None))
        ticket = line.join(token, language)
        return JSONResponse(content=await hold(tenant_id, script_id, ticket, line.position(ticket.id), True))

    @app.post("/v1/voice/web/{token}/wait")
    async def wait(token: str, request: Request) -> JSONResponse:
        """Polled every few seconds while queued. Starts the call when it is this caller's turn."""
        tenant_id, script_id = link(request, token)
        ticket_id = request.query_params.get("ticket") or ""
        ticket = line.waiting.get(ticket_id)
        if ticket is None or ticket.link != token:
            raise CloudiatorError(404, "ticket_expired", "Your place in line expired. Please call again.")
        turn_ticket = line.take_turn(ticket_id)
        if turn_ticket is not None:
            request.state.usage.tool = "voice_web_start"
            call_sid, reply = begin(tenant_id, script_id, turn_ticket.language)
            return JSONResponse(content=await _turn(audio, tenant_id, call_sid, reply, store, heard=None))
        return JSONResponse(content=await hold(tenant_id, script_id, ticket, line.position(ticket_id), False))

    @app.post("/v1/voice/web/{token}/leave")
    async def leave(token: str, request: Request) -> JSONResponse:
        link(request, token)
        ticket = line.waiting.get(request.query_params.get("ticket") or "")
        if ticket is not None and ticket.link == token:
            line.leave(ticket.id)
        return JSONResponse(content={"left": True})

    @app.post("/v1/voice/web/{token}/hangup")
    async def hangup(token: str, request: Request) -> JSONResponse:
        """The caller hung up or closed the page: free the line for the next person."""
        tenant_id, script_id = link(request, token)
        call_sid = request.query_params.get("call_id") or ""
        session = store.session_by_call(call_sid) if call_sid.startswith("WB") else None
        if session is None or session["tenant_id"] != tenant_id or session["to_number"] != f"web:{script_id}":
            raise CloudiatorError(404, "call_not_found", "Call not found.")
        line.ended(call_sid)
        if session["status"] == "in_progress":
            store.update_session(session["id"], status="abandoned", current_step=None)
        return JSONResponse(content={"ended": True})

    @app.get("/v1/voice/web/{token}/line")
    async def line_status(token: str, request: Request) -> JSONResponse:
        link(request, token)
        return JSONResponse(content=line.snapshot())

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
        try:
            turn_no = int(params["turn"]) if params.get("turn") else None
        except ValueError as exc:
            raise CloudiatorError(400, "invalid_request_error", "turn must be an integer.") from exc
        if call_sid in line.active:
            line.touch(call_sid)
        elif line.free():
            line.started(call_sid)  # the page went quiet long enough to lose the slot; it is back
        else:
            raise CloudiatorError(409, "call_expired", "This call timed out and the line is now busy. Please call again.")

        answer = await request.body()
        if len(answer) > settings.voice_web_max_audio_bytes:
            raise CloudiatorError(413, "request_too_large", "Audio is too long for one answer.")
        request.state.usage.tool = "voice_web_turn"
        # A retry of an answered turn replays without transcribing again.
        cached = store.reply_for(call_sid, f"{step}#{turn_no}" if turn_no is not None else step, attempt)
        if cached is not None:
            return JSONResponse(content=await _turn(audio, tenant_id, call_sid, cached, store, heard=None))
        try:
            heard = await speech.transcribe(
                answer, language=session_language(session), settings=settings
            )
        except speech.SpeechUnavailable as exc:
            log.error("speech recognition unavailable: %s", exc)
            raise CloudiatorError(
                503, "speech_unavailable", "Speech recognition is not set up on this appliance.",
                error_type="server_error",
            ) from exc
        reply = engine.on_gather(call_sid=call_sid, step=step, attempt=attempt, speech=heard, turn=turn_no)
        if any(verb.get("hangup") for verb in reply["verbs"]):
            line.ended(call_sid)
        return JSONResponse(content=await _turn(audio, tenant_id, call_sid, reply, store, heard=heard))


async def _turn(audio, tenant_id: str, call_sid: str, reply: dict[str, Any], store, *, heard: str | None) -> dict[str, Any]:
    """Reply → what the page plays: ordered clips, then listen or hang up."""
    session = store.session_by_call(call_sid)
    script = session["definition"] if session else {"id": reply.get("script_id") or ""}
    language = reply.get("language") or "en-US"
    clips = []
    listen = None
    done = False
    for verb in reply["verbs"]:
        gather = verb.get("gather") or {}
        text = verb.get("say") or gather.get("prompt")
        if text:
            data_url, source = await audio.clip(
                tenant_id=tenant_id, script=script, key=verb.get("key") or gather.get("step"),
                language=language, text=text,
            )
            clips.append({"text": text, "audio": data_url, "source": source})
        if gather:
            listen = {
                "step": gather["step"],
                "attempt": gather["attempt"],
                "turn": gather.get("turn"),
                "timeout": gather["timeout"],
                "speech_timeout": gather["speech_timeout"],
            }
        if verb.get("hangup"):
            done = True
    return {"call_id": call_sid, "language": language, "heard": heard, "clips": clips, "listen": listen, "done": done}


def _client_ip(request: Request) -> str:
    # Behind cloudflared every request is from 127.0.0.1; Cloudflare sets this.
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
