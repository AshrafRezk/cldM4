"""A HEIC frame converts to JPEG without loading a model."""

from __future__ import annotations

import base64
import io

from PIL import Image

from app import main


def _heic_b64() -> str:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    image = Image.new("RGB", (32, 24), (20, 80, 160))
    buffer = io.BytesIO()
    image.save(buffer, format="HEIF")
    return base64.b64encode(buffer.getvalue()).decode()


async def test_heic_converts_to_jpeg(make_client, install_key):
    _record, headers = install_key(capabilities=["tools.image_ops"])
    body = {"action": "convert", "format": "jpeg", "image_base64": _heic_b64()}
    async with make_client(headers) as client:
        response = await client.post("/v1/tools/image", json=body)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["format"] == "jpeg"
        assert payload["width"] == 32
        assert payload["height"] == 24
        path = payload["url"].removeprefix(main.settings.public_base_url)
        jpeg = await client.get(path)
    assert jpeg.status_code == 200
    assert jpeg.content[:2] == b"\xff\xd8"
    opened = Image.open(io.BytesIO(jpeg.content))
    assert opened.size == (32, 24)


async def test_gps_is_stripped_by_default(make_client, install_key):
    image = Image.new("RGB", (8, 8), "white")
    exif = image.getexif()
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = 30.0
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    _record, headers = install_key(capabilities=["tools.image_ops"])
    body = {"action": "exif", "image_base64": base64.b64encode(buffer.getvalue()).decode()}
    async with make_client(headers) as client:
        response = await client.post("/v1/tools/image", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["had_gps"] is True
        assert response.json()["stripped"] is True
        path = response.json()["url"].removeprefix(main.settings.public_base_url)
        cleaned = await client.get(path)
    opened = Image.open(io.BytesIO(cleaned.content))
    assert not opened.getexif().get_ifd(0x8825)
