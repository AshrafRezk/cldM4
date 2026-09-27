"""QR encode then decode returns the same text."""

from __future__ import annotations

import base64

from app import main


async def test_qr_roundtrip(make_client, install_key):
    _record, headers = install_key(capabilities=["tools.image_ops"])
    async with make_client(headers) as client:
        encoded = await client.post(
            "/v1/tools/image",
            json={"action": "qr_encode", "text": "INVOICE 42"},
        )
        assert encoded.status_code == 200, encoded.text
        path = encoded.json()["url"].removeprefix(main.settings.public_base_url)
        png = await client.get(path)
        assert png.content.startswith(b"\x89PNG")
        decoded = await client.post(
            "/v1/tools/image",
            json={"action": "qr_decode", "image_base64": base64.b64encode(png.content).decode()},
        )
    assert decoded.status_code == 200, decoded.text
    assert decoded.json()["text"] == "INVOICE 42"
