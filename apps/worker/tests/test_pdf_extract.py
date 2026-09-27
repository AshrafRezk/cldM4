"""PDF text comes back from the file, not from a model."""

from __future__ import annotations

import base64

from fpdf import FPDF

from app import main
from tools.document.handler import PREVIEW_CHARS


def _pdf(text: str) -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16)
    pdf.multi_cell(0, 8, text)
    return base64.b64encode(bytes(pdf.output())).decode()


async def test_pdf_text_extracts(make_client, install_key):
    _record, headers = install_key(capabilities=["tools.docs"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/tools/document",
            json={"filename": "invoice.pdf", "file_base64": _pdf("INVOICE 42")},
        )
    assert response.status_code == 200, response.text
    assert "INVOICE 42" in response.json()["text"]
    assert response.json()["truncated"] is False


async def test_a_long_extract_is_a_preview_plus_artifact(make_client, install_key, monkeypatch):
    monkeypatch.setattr("tools.document.handler.PREVIEW_CHARS", 20)
    _record, headers = install_key(capabilities=["tools.docs"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/tools/document",
            json={"filename": "note.txt", "file_base64": base64.b64encode(b"A" * 100).decode()},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["truncated"] is True
        assert len(body["text"]) == 20
        assert body["chars"] == 100
        path = body["url"].removeprefix(main.settings.public_base_url)
        full = await client.get(path)
    assert full.status_code == 200
    assert full.content == b"A" * 100
    assert PREVIEW_CHARS == 8_000
