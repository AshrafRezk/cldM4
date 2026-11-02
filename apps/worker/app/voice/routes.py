"""Voice routes. Salesforce side: Bearer + `voice`. Twilio side: signature only.

Twilio routes are not in any OpenAPI fragment; Apex never calls TwiML.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from ..errors import CloudiatorError, not_supported
from .crm import transcript_text
from .engine import ScriptInvalid, VoiceEngine, validate_script
from .store import NumberTaken, iso

SALESFORCE_ID = re.compile(r"^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$")
SESSION_STATUSES = {"in_progress", "ready_to_commit", "committed", "abandoned"}
TWIML = "application/xml"


def register_voice_routes(app: FastAPI, *, engine: VoiceEngine, settings, require_key) -> None:
    store = engine.store

    @app.post("/v1/voice/scripts")
    async def publish_script(request: Request, key=Depends(require_key("voice"))) -> JSONResponse:
        body = await _json(request)
        # Apex sends Definition__c as a string so External Services can type it.
        if isinstance(body.get("definition"), str):
            try:
                body = json.loads(body["definition"])
            except ValueError as exc:
                raise CloudiatorError(
                    400, "invalid_request_error", "definition is not valid JSON.", param="definition"
                ) from exc
        try:
            script = validate_script(body)
        except ScriptInvalid as exc:
            raise CloudiatorError(400, "invalid_request_error", str(exc), param=exc.param) from exc
        request.state.usage.tool = "voice_publish"
        try:
            result = store.upsert_script(key.tenant_id, script)
        except NumberTaken as exc:
            raise CloudiatorError(
                409,
                "number_in_use",
                f"{exc} already answers for another tenant.",
                param="inbound_numbers",
            ) from exc
        return JSONResponse(content=result)

    @app.get("/v1/voice/scripts")
    async def list_scripts(key=Depends(require_key("voice"))) -> JSONResponse:
        return JSONResponse(content={"object": "list", "data": store.list_scripts(key.tenant_id)})

    @app.get("/v1/voice/sessions")
    async def list_sessions(request: Request, key=Depends(require_key("voice"))) -> JSONResponse:
        status = request.query_params.get("status") or None
        if status is not None and status not in SESSION_STATUSES:
            raise CloudiatorError(
                400, "invalid_request_error", f"status must be one of {sorted(SESSION_STATUSES)}.",
                param="status",
            )
        rows = store.list_sessions(key.tenant_id, status=status)
        return JSONResponse(content={"object": "list", "data": [public_session(r) for r in rows]})

    @app.get("/v1/voice/sessions/{session_id}")
    async def get_session(session_id: str, key=Depends(require_key("voice"))) -> JSONResponse:
        return JSONResponse(content=public_session(_owned(store, key, session_id)))

    @app.post("/v1/voice/sessions/{session_id}/ack")
    async def ack_session(
        session_id: str, request: Request, key=Depends(require_key("voice"))
    ) -> JSONResponse:
        session = _owned(store, key, session_id)
        ids = _record_ids(await _json(request))
        if session["status"] == "committed":
            if session["committed_ids"] == ids:
                return JSONResponse(content=public_session(session))
            raise CloudiatorError(409, "already_committed", "This session was already acked.")
        if session["status"] != "ready_to_commit":
            raise CloudiatorError(
                409, "not_ready", f"Session is {session['status']}, not ready_to_commit."
            )
        store.update_session(
            session["id"], status="committed", committed_ids=ids, acked_at=time.time()
        )
        request.state.usage.tool = "voice_ack"
        return JSONResponse(content=public_session(store.get_session(key.tenant_id, session_id)))

    @app.post("/v1/voice/calls")
    async def outbound_call(key=Depends(require_key("voice"))) -> JSONResponse:
        del key
        raise not_supported(
            "Outbound calls are a later campaign phase. Inbound scripts work today.",
            status_code=501,
        )

    # Twilio ------------------------------------------------------------------

    async def twilio_form(request: Request) -> dict[str, str]:
        if not settings.twilio_auth_token:
            raise CloudiatorError(
                503, "voice_not_configured", "TWILIO_AUTH_TOKEN is not set on this appliance.",
                error_type="server_error",
            )
        form = await request.form()
        params = [(name, str(value)) for name, value in form.multi_items()]
        url = settings.public_base_url.rstrip("/") + request.url.path
        if request.url.query:
            url += "?" + request.url.query
        from .twilio_sig import is_valid

        if not is_valid(
            settings.twilio_auth_token, url, params, request.headers.get("x-twilio-signature")
        ):
            raise CloudiatorError(403, "invalid_signature", "Twilio signature check failed.")
        return dict(params)

    @app.post("/v1/voice/twilio/inbound")
    async def twilio_inbound(request: Request) -> Response:
        form = await twilio_form(request)
        request.state.usage.tool = "voice_inbound"
        call_sid = _required(form, "CallSid")
        reply = engine.on_inbound(
            call_sid=call_sid, from_number=form.get("From", ""), to_number=form.get("To", "")
        )
        return Response(content=reply, media_type=TWIML)

    @app.post("/v1/voice/twilio/gather")
    async def twilio_gather(request: Request) -> Response:
        form = await twilio_form(request)
        request.state.usage.tool = "voice_gather"
        step = request.query_params.get("step") or ""
        try:
            attempt = int(request.query_params.get("attempt") or "1")
        except ValueError as exc:
            raise CloudiatorError(400, "invalid_request_error", "attempt must be an integer.") from exc
        reply = engine.on_gather(
            call_sid=_required(form, "CallSid"),
            step=step,
            attempt=attempt,
            speech=form.get("SpeechResult", ""),
        )
        return Response(content=reply, media_type=TWIML)

    @app.post("/v1/voice/twilio/recording")
    async def twilio_recording(request: Request) -> Response:
        form = await twilio_form(request)
        engine.on_recording(
            call_sid=_required(form, "CallSid"), recording_url=form.get("RecordingUrl", "")
        )
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response/>', media_type=TWIML)


def public_session(session: dict[str, Any]) -> dict[str, Any]:
    commit = session.get("commit_doc")
    ids = session.get("committed_ids")
    return {
        "id": session["id"],
        "call_sid": session["call_sid"],
        "from": session.get("from_number"),
        "to": session.get("to_number"),
        "script_id": session["script_id"],
        "script_version": session["script_version"],
        "status": session["status"],
        "current_step": session.get("current_step"),
        "answers": session.get("answers") or {},
        "transcript": transcript_text(session.get("turns") or []),
        "recording_url": session.get("recording_url"),
        "commit": commit,
        # The same document as a string: Apex deserializes it untyped, and the
        # External Services importer cannot type sObject field maps.
        "commit_json": json.dumps(commit, ensure_ascii=False) if commit is not None else None,
        "committed_ids": ids,
        "created_at": iso(session.get("created_at")),
        "updated_at": iso(session.get("updated_at")),
    }


def _owned(store, key, session_id: str) -> dict[str, Any]:
    session = store.get_session(key.tenant_id, session_id)
    if session is None:
        raise CloudiatorError(404, "session_not_found", "Voice session not found.")
    return session


def _record_ids(body: dict[str, Any]) -> dict[str, str]:
    """`record_ids` map, or `records: [{sobject, id}]` for External Services."""
    ids: dict[str, str] = {}
    if isinstance(body.get("record_ids"), dict):
        ids.update(body["record_ids"])
    for item in body.get("records") or []:
        if isinstance(item, dict):
            ids[str(item.get("sobject"))] = item.get("id")
    if not ids:
        raise CloudiatorError(
            400, "invalid_request_error", "Send record_ids or records.", param="record_ids"
        )
    for sobject, record_id in ids.items():
        if not isinstance(record_id, str) or not SALESFORCE_ID.match(record_id):
            raise CloudiatorError(
                400, "invalid_request_error", f"{sobject} id is not a Salesforce Id.",
                param="record_ids",
            )
    return ids


def _required(form: dict[str, str], name: str) -> str:
    value = form.get(name)
    if not value:
        raise CloudiatorError(400, "invalid_request_error", f"{name} is required.", param=name)
    return value


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise CloudiatorError(400, "invalid_request_error", "Body must be JSON.") from exc
    if not isinstance(body, dict):
        raise CloudiatorError(400, "invalid_request_error", "Body must be a JSON object.")
    return body
