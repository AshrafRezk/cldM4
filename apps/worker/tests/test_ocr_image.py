"""ocrmac must receive a PIL image. A pathlib.Path never reaches Vision."""

from __future__ import annotations

import io
import sys
import types

from PIL import Image


def test_vision_passes_ocrmac_a_pil_image(monkeypatch):
    seen: dict[str, object] = {}

    class OCR:
        def __init__(self, image, *args, **kwargs):
            del args, kwargs
            seen["kind"] = type(image).__name__
            seen["size"] = image.size

        def recognize(self):
            return [("INVOICE 42", 0.99, (0, 0, 1, 1))]

    fake = types.ModuleType("ocrmac")
    fake.ocrmac = types.SimpleNamespace(OCR=OCR)
    monkeypatch.setitem(sys.modules, "ocrmac", fake)

    from tools.ocr.handler import _vision

    buffer = io.BytesIO()
    Image.new("RGB", (32, 16), "white").save(buffer, format="PNG")
    assert _vision(buffer.getvalue()) == "INVOICE 42"
    assert seen == {"kind": "Image", "size": (32, 16)}
