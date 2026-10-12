"""HTTP + WebSocket routes for the SIM phone agent."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse

from .errors import CloudiatorError
from .tts import build_tts_provider, normalize_language, pcm16_to_wav, resolve_voice
from .voice import VoiceManager, parse_script_body
from .whisper import DEFAULT_MODEL_NAME, transcribe_bytes


def register_voice_routes(
    app: FastAPI,
    *,
    voice: VoiceManager,
    require_key: Callable[..., Any],
    settings,
    scheduler,
) -> None:
    @app.post("/v1/audio/transcriptions")
    async def audio_transcriptions(
        request: Request,
        file: UploadFile = File(...),
        model: str | None = Form(default=None),
        language: str | None = Form(default=None),
        key=Depends(require_key("transcriptions")),
    ) -> JSONResponse:
        data = await file.read()
        request.state.usage.model = model or DEFAULT_MODEL_NAME
        result = await transcribe_bytes(
            data,
            settings=settings,
            scheduler=scheduler,
            filename=file.filename,
            content_type=file.content_type,
            language=language,
        )
        return JSONResponse(
            content={
                "text": result["text"],
                "language": result.get("language"),
                "model": result.get("model") or DEFAULT_MODEL_NAME,
            }
        )

    @app.post("/v1/audio/speech")
    async def audio_speech(request: Request, key=Depends(require_key("tts"))) -> JSONResponse:
        body = await _json(request)
        text = body.get("input") or body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CloudiatorError(400, "invalid_request_error", "input is required.", param="input")
        language = normalize_language(body.get("language") or "en")
        voice_id = body.get("voice")
        if voice_id is not None and not isinstance(voice_id, str):
            raise CloudiatorError(
                400, "invalid_request_error", "voice must be a string.", param="voice"
            )
        provider = build_tts_provider(settings)
        pcm = await provider.synthesize(text.strip(), language=language, voice=voice_id)
        wav = pcm16_to_wav(pcm)
        artifact_id = voice.artifacts.save(wav, ".wav")
        return JSONResponse(
            content={
                "id": artifact_id,
                "url": voice.artifacts.sign(artifact_id),
                "voice": resolve_voice(language, voice_id),
                "language": language,
                "format": "wav",
            }
        )

    @app.post("/v1/voice/lines")
    async def create_line(request: Request, key=Depends(require_key("voice_calls"))) -> JSONResponse:
        body = await _json(request)
        script = None
        if body.get("script"):
            script = parse_script_body(body)
        line = voice.register_line(
            line_id=body.get("line_id"),
            e164=body.get("e164") or body.get("number") or "",
            token=body.get("token"),
            key_id=key.key_id,
            tenant_id=key.tenant_id,
            script=script,
        )
        payload = line.public()
        # Show the line token once at creation so the handset can be configured.
        payload["token"] = line.token
        return JSONResponse(status_code=201, content=payload)

    @app.get("/v1/voice/lines")
    async def list_lines(key=Depends(require_key("voice_calls"))) -> JSONResponse:
        lines = [line.public() for line in voice.list_lines(key_id=key.key_id)]
        return JSONResponse(content={"data": lines})

    @app.get("/v1/voice/lines/{line_id}")
    async def get_line(line_id: str, key=Depends(require_key("voice_calls"))) -> JSONResponse:
        line = voice.get_line(line_id)
        if line.key_id and line.key_id != key.key_id:
            raise CloudiatorError(404, "not_found", "Line not found.")
        return JSONResponse(content=line.public())

    @app.put("/v1/voice/lines/{line_id}/script")
    async def put_script(
        line_id: str, request: Request, key=Depends(require_key("voice_calls"))
    ) -> JSONResponse:
        body = await _json(request)
        script = parse_script_body(body)
        line = voice.set_script(line_id, script, key_id=key.key_id)
        return JSONResponse(content=line.public())

    @app.post("/v1/voice/calls")
    async def create_call(request: Request, key=Depends(require_key("voice_calls"))) -> JSONResponse:
        body = await _json(request)
        line_id = body.get("line_id")
        if not isinstance(line_id, str) or not line_id.strip():
            raise CloudiatorError(
                400, "invalid_request_error", "line_id is required.", param="line_id"
            )
        script_body = body
        if not body.get("script"):
            line = voice.get_line(line_id.strip())
            if line.script is None:
                raise CloudiatorError(
                    400,
                    "invalid_request_error",
                    "script is required when the line has no default script.",
                    param="script",
                )
            script_body = {
                "script": line.script.script,
                "language": body.get("language") or line.script.language,
                "greeting": body.get("greeting") if "greeting" in body else line.script.greeting,
                "voice": body.get("voice") or line.script.voice,
                "max_turns": body.get("max_turns") or line.script.max_turns,
            }
        parsed = parse_script_body(script_body)
        call = await voice.start_outbound(
            line_id=line_id.strip(),
            to_number=body.get("to") or body.get("to_number") or "",
            script=parsed.script,
            language=parsed.language,
            greeting=parsed.greeting,
            voice=parsed.voice,
            max_turns=parsed.max_turns,
            key_id=key.key_id,
            tenant_id=key.tenant_id,
        )
        return JSONResponse(status_code=202, content=call.public())

    @app.get("/v1/voice/calls/{call_id}")
    async def get_call(call_id: str, key=Depends(require_key("voice_calls"))) -> JSONResponse:
        return JSONResponse(content=voice.get_call(call_id, key_id=key.key_id))

    @app.post("/v1/voice/calls/{call_id}/hangup")
    async def hangup_call(call_id: str, key=Depends(require_key("voice_calls"))) -> JSONResponse:
        call = await voice.hangup(call_id, key_id=key.key_id)
        return JSONResponse(content=call.public())

    @app.websocket("/v1/voice/lines/{line_id}/media")
    async def media_socket(websocket: WebSocket, line_id: str) -> None:
        token = websocket.query_params.get("token") or websocket.headers.get("x-voice-line-token")
        await voice.handle_media(websocket, line_id, token)


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise CloudiatorError(
            400, "invalid_request_error", "The request body is not valid JSON."
        ) from exc
    if not isinstance(body, dict):
        raise CloudiatorError(400, "invalid_request_error", "JSON body must be an object.")
    return body
