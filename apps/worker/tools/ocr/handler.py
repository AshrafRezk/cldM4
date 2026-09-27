"""Apple Vision OCR. No model weights. gpu is false."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from app.errors import CloudiatorError
from app.ssrf import fetch_image

NAME = "ocr_image"
CAPABILITY = "tools.ocr"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any], *, settings, image_bytes: bytes | None = None) -> dict[str, Any]:
    data = image_bytes
    if data is None:
        url = arguments.get("image_url")
        if not isinstance(url, str) or not url:
            raise CloudiatorError(400, "invalid_request_error", "image_url is required.", param="image_url")
        fetched = await fetch_image(
            url,
            max_bytes=settings.vision_max_bytes,
            timeout=settings.vision_fetch_timeout_seconds,
            max_redirects=settings.vision_max_redirects,
        )
        data = fetched.data
    text = await asyncio.to_thread(_recognize, data)
    return {"text": text}


def _recognize(data: bytes) -> str:
    """Vision on macOS. Tests inject CLOUDIATOR_OCR_BACKEND; Linux has no Vision."""
    backend = _backend()
    return backend(data)


def _backend():
    import os

    name = os.environ.get("CLOUDIATOR_OCR_BACKEND")
    if name:
        module_name, _, attr = name.partition(":")
        import importlib

        module = importlib.import_module(module_name)
        return getattr(module, attr or "recognize")
    return _vision


def _vision(data: bytes) -> str:
    try:
        from ocrmac import ocrmac
    except ImportError as exc:
        raise CloudiatorError(
            503,
            "not_supported",
            "Apple Vision OCR is only available on the Mini.",
            error_type="server_error",
        ) from exc
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as handle:
        handle.write(data)
        handle.flush()
        lines = ocrmac.OCR(Path(handle.name)).recognize()
    parts = []
    for line in lines or []:
        text = line[0] if isinstance(line, (list, tuple)) else str(line)
        if text:
            parts.append(str(text))
    return "\n".join(parts)
