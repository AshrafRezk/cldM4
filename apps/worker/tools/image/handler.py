"""Image convert, QR, EXIF, palette. No generative model. GPS is stripped by default."""

from __future__ import annotations

import base64
import io
from typing import Any

from app.errors import CloudiatorError

NAME = "image_transform"
CAPABILITY = "tools.image_ops"
TIMEOUT_SECONDS = 30
GPU = False

_ACTIONS = {"convert", "qr_encode", "qr_decode", "exif", "palette"}
_FORMATS = {"jpeg": "JPEG", "jpg": "JPEG", "png": "PNG", "heic": "HEIF"}


async def run(arguments: dict[str, Any], *, settings, artifacts) -> dict[str, Any]:
    action = arguments.get("action") or "convert"
    if action not in _ACTIONS:
        raise CloudiatorError(
            400,
            "invalid_request_error",
            "action must be convert, qr_encode, qr_decode, exif, or palette.",
            param="action",
        )
    if action == "qr_encode":
        return _qr_encode(arguments, artifacts)
    data = _decode(arguments.get("image_base64"), limit=settings.vision_max_bytes)
    if action == "qr_decode":
        return {"text": _qr_decode(data)}
    if action == "palette":
        return {"colors": _palette(data, arguments.get("count") or 5)}
    if action == "exif":
        return _exif(data, artifacts, strip=_strip_flag(arguments))
    return _convert(data, artifacts, arguments.get("format") or "jpeg", strip=_strip_flag(arguments))


def _strip_flag(arguments: dict[str, Any]) -> bool:
    flag = arguments.get("strip_gps", True)
    if isinstance(flag, bool):
        return flag
    raise CloudiatorError(400, "invalid_request_error", "strip_gps must be a boolean.", param="strip_gps")


def _decode(value: Any, *, limit: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise CloudiatorError(400, "invalid_request_error", "image_base64 is required.", param="image_base64")
    try:
        data = base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise CloudiatorError(400, "invalid_request_error", "image_base64 is not valid.", param="image_base64") from exc
    if len(data) > limit:
        raise CloudiatorError(413, "upload_too_large", f"Upload exceeds {limit} bytes.")
    return data


def _open(data: bytes):
    _register_heif()
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise CloudiatorError(400, "invalid_request_error", "The image could not be decoded.", param="image_base64") from exc
    return image


def _register_heif() -> None:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()


def _convert(data: bytes, artifacts, fmt: str, *, strip: bool) -> dict[str, Any]:
    pil_format = _FORMATS.get(str(fmt).lower())
    if pil_format is None:
        raise CloudiatorError(400, "invalid_request_error", "format must be jpeg, png, or heic.", param="format")
    image = _without_gps(_open(data)) if strip else _open(data)
    if pil_format == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    payload = _save(image, pil_format)
    suffix = ".jpg" if pil_format == "JPEG" else ".png" if pil_format == "PNG" else ".heic"
    artifact_id = artifacts.save(payload, suffix)
    return {
        "id": artifact_id,
        "url": artifacts.sign(artifact_id),
        "format": fmt.lower(),
        "width": image.size[0],
        "height": image.size[1],
    }


def _exif(data: bytes, artifacts, *, strip: bool) -> dict[str, Any]:
    image = _open(data)
    had_gps = _has_gps(image)
    cleaned = _without_gps(image) if strip else image
    payload = _save(cleaned.convert("RGB"), "JPEG")
    artifact_id = artifacts.save(payload, ".jpg")
    return {
        "id": artifact_id,
        "url": artifacts.sign(artifact_id),
        "had_gps": had_gps,
        "stripped": bool(strip and had_gps),
    }


def _has_gps(image) -> bool:
    exif = image.getexif()
    gps = exif.get_ifd(0x8825) if exif else {}
    return bool(gps)


def _without_gps(image):
    exif = image.getexif()
    if exif and 0x8825 in exif:
        del exif[0x8825]
    clone = image.copy()
    clone.info.pop("exif", None)
    return clone


def _save(image, pil_format: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=pil_format)
    return buffer.getvalue()


def _qr_encode(arguments: dict[str, Any], artifacts) -> dict[str, Any]:
    text = arguments.get("text")
    if not isinstance(text, str) or not text:
        raise CloudiatorError(400, "invalid_request_error", "text is required.", param="text")
    if len(text) > 2000:
        raise CloudiatorError(400, "invalid_request_error", "text is capped at 2000 characters.", param="text")
    import qrcode

    image = qrcode.make(text).convert("RGB")
    payload = _save(image, "PNG")
    artifact_id = artifacts.save(payload, ".png")
    return {"id": artifact_id, "url": artifacts.sign(artifact_id), "text": text}


def _qr_decode(data: bytes) -> str:
    import cv2
    import numpy as np

    image = _open(data).convert("RGB")
    array = np.array(image)
    text, _points, _ = cv2.QRCodeDetector().detectAndDecode(array)
    if not text:
        raise CloudiatorError(400, "invalid_request_error", "No QR code was found in the image.")
    return text


def _palette(data: bytes, count: Any) -> list[str]:
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 16:
        raise CloudiatorError(400, "invalid_request_error", "count must be an integer from 1 to 16.", param="count")
    image = _open(data).convert("RGB")
    colors = image.getcolors(image.size[0] * image.size[1]) or []
    colors.sort(key=lambda item: item[0], reverse=True)
    return [_hex(rgb) for _n, rgb in colors[:count]]


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)
