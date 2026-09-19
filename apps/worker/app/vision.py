"""Downscale vision inputs: long edge ≤ 1024, JPEG q85, EXIF stripped."""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps

from app.config import Settings
from app.errors import not_supported, url_not_allowed
from app.ssrf import load_image_bytes


def downscale_image(raw: bytes, settings: Settings) -> bytes:
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise url_not_allowed("Image bytes could not be decoded") from exc
    image = ImageOps.exif_transpose(image)
    image.info.pop("exif", None)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    width, height = image.size
    long_edge = max(width, height)
    if long_edge > settings.vision_max_edge_px:
        scale = settings.vision_max_edge_px / float(long_edge)
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=settings.vision_jpeg_quality, optimize=True)
    return out.getvalue()


def collect_image_urls(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    urls: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") != "image_url":
            continue
        image_url = part.get("image_url")
        if isinstance(image_url, str):
            urls.append(image_url)
        elif isinstance(image_url, dict) and "url" in image_url:
            urls.append(str(image_url["url"]))
        else:
            raise url_not_allowed("image_url part is missing url")
    return urls


async def prepare_images(
    content: Any,
    settings: Settings,
    *,
    vision_supported: bool,
) -> list[bytes]:
    urls = collect_image_urls(content)
    if not urls:
        return []
    if not vision_supported:
        raise not_supported(
            "This model has no vision capability. Use POST /v1/tools/ocr (Phase D) "
            "or enable a VLM in slot 1.",
            param="messages",
            status_code=404,
        )
    if len(urls) > settings.vision_max_images:
        raise url_not_allowed(
            f"At most {settings.vision_max_images} images per request",
            param="messages",
        )
    prepared: list[bytes] = []
    for url in urls:
        raw = await load_image_bytes(url, settings)
        prepared.append(downscale_image(raw, settings))
    return prepared
