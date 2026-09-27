"""REST surface for Phase D tools. The chat loop calls the same handlers."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .artifacts import content_headers
from .errors import CloudiatorError, upload_too_large


def register_tool_routes(app: FastAPI, *, artifacts, runner, require_key) -> None:
    settings = runner.settings

    @app.post("/v1/tools/ocr")
    async def ocr(request: Request, key=Depends(require_key("tools.ocr"))) -> JSONResponse:
        image, arguments = await _ocr_input(request, settings)
        request.state.usage.tool = "ocr_image"
        result = await runner.execute("ocr_image", arguments, key, image_bytes=image)
        if result.get("error"):
            raise CloudiatorError(400, result["error"], result.get("message") or "OCR failed.")
        return JSONResponse(content=result)

    @app.post("/v1/tools/geocode")
    async def geocode(request: Request, key=Depends(require_key("tools.maps"))) -> JSONResponse:
        body = await _json(request)
        request.state.usage.tool = "geocode"
        result = await runner.execute("geocode", body, key)
        return _tool_json(result)

    @app.post("/v1/tools/places")
    async def places(request: Request, key=Depends(require_key("tools.maps"))) -> JSONResponse:
        body = await _json(request)
        request.state.usage.tool = "places_nearby"
        result = await runner.execute("places_nearby", body, key)
        return _tool_json(result)

    @app.post("/v1/tools/route")
    async def route(request: Request, key=Depends(require_key("tools.maps"))) -> JSONResponse:
        body = await _json(request)
        request.state.usage.tool = "route"
        result = await runner.execute("route", body, key)
        return _tool_json(result)

    @app.post("/v1/artifacts/{artifact_id}/sign")
    async def sign_artifact(
        artifact_id: str, request: Request, key=Depends(require_key())
    ) -> JSONResponse:
        del key
        request.state.usage.tool = "artifact_sign"
        url = artifacts.sign(artifact_id)
        return JSONResponse(
            content={
                "id": artifact_id,
                "url": url,
                "expires_in": settings.artifact_url_ttl_seconds,
            }
        )

    @app.get("/artifacts/{artifact_id}")
    async def fetch_artifact(artifact_id: str, request: Request) -> Response:
        path = artifacts.verify(
            artifact_id,
            request.query_params.get("exp", ""),
            request.query_params.get("sig", ""),
        )
        return Response(content=path.read_bytes(), headers=content_headers(path))


def _tool_json(result: dict[str, Any]) -> JSONResponse:
    if result.get("error") == "scope_denied":
        raise CloudiatorError(403, "scope_denied", result.get("message") or "Scope denied.")
    if result.get("error"):
        code = result["error"]
        status = 429 if code == "insufficient_quota" else 400
        if code == "not_found":
            status = 404
        raise CloudiatorError(status, code, result.get("message") or "Tool failed.")
    return JSONResponse(content=result)


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise CloudiatorError(400, "invalid_request_error", "Body must be JSON.") from exc
    if not isinstance(body, dict):
        raise CloudiatorError(400, "invalid_request_error", "Body must be a JSON object.")
    return body


async def _ocr_input(request: Request, settings) -> tuple[bytes | None, dict[str, Any]]:
    content_type = request.headers.get("content-type", "")
    limit = settings.vision_max_bytes
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise CloudiatorError(400, "invalid_request_error", "file is required.", param="file")
        data = await upload.read()
        if len(data) > limit:
            raise upload_too_large(limit)
        return data, {}
    body = await _json(request)
    if body.get("image_url"):
        return None, {"image_url": body["image_url"]}
    raw = body.get("image_base64")
    if isinstance(raw, str) and raw:
        import base64

        try:
            data = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise CloudiatorError(400, "invalid_request_error", "image_base64 is not valid.") from exc
        if len(data) > limit:
            raise upload_too_large(limit)
        return data, {}
    raise CloudiatorError(
        400, "invalid_request_error", "Send file, image_url, or image_base64.", param="file"
    )
