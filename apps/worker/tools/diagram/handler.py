"""Diagrams. Graphviz is the default. mermaid-cli is off unless ENABLE_MERMAID=true."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.errors import CloudiatorError
from app.procgroup import run_group

NAME = "render_diagram"
CAPABILITY = "tools.diagrams"
TIMEOUT_SECONDS = 30
GPU = False

_MAX_SOURCE = 64_000
_BLOCKED = ("shapefile", "image=", "`")
_CHROMIUM_ARGS = ["--no-sandbox", "--single-process", "--disable-dev-shm-usage"]
# launchd does not inherit the login PATH, so Homebrew's dot is invisible to
# `shutil.which` inside the worker even when Terminal can run it.
_DOT_CANDIDATES = ("/opt/homebrew/bin/dot", "/usr/local/bin/dot")


async def run(arguments: dict[str, Any], *, settings, artifacts, scheduler=None) -> dict[str, Any]:
    source = _source(arguments.get("source"))
    engine = arguments.get("engine") or "graphviz"
    if engine not in {"graphviz", "mermaid"}:
        raise CloudiatorError(400, "invalid_request_error", "engine must be graphviz or mermaid.", param="engine")
    if engine == "mermaid" and settings.enable_mermaid:
        if scheduler is None:
            png = await _graphviz(source)
            used = "graphviz"
        else:
            async with scheduler.cpu_heavy_slot():
                png, used = await _mermaid_or_graphviz(source)
    else:
        png = await _graphviz(source)
        used = "graphviz"
    artifact_id = artifacts.save(png, ".png")
    return {"id": artifact_id, "url": artifacts.sign(artifact_id), "engine": used}


def _source(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CloudiatorError(400, "invalid_request_error", "source is required.", param="source")
    if len(value) > _MAX_SOURCE:
        raise CloudiatorError(400, "invalid_request_error", "source is too long.", param="source")
    lowered = value.lower()
    for token in _BLOCKED:
        if token in lowered:
            raise CloudiatorError(400, "invalid_request_error", "source includes a blocked diagram feature.", param="source")
    return value


def graphviz_dot() -> str:
    found = shutil.which("dot")
    if found:
        return found
    for candidate in _DOT_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError("dot")


async def _graphviz(source: str) -> bytes:
    try:
        dot = graphviz_dot()
    except FileNotFoundError as exc:
        raise CloudiatorError(
            503,
            "not_supported",
            "Graphviz (dot) is not installed on the Mini. brew install graphviz, "
            "then restart the worker. LaunchAgent jobs do not see a Terminal PATH.",
            error_type="server_error",
        ) from exc
    try:
        stdout, stderr, code = await run_group([dot, "-Tpng"], timeout=30, stdin=source.encode())
    except FileNotFoundError as exc:
        raise CloudiatorError(
            503,
            "not_supported",
            "Graphviz (dot) is not installed on the Mini.",
            error_type="server_error",
        ) from exc
    except TimeoutError as exc:
        raise CloudiatorError(400, "tool_timeout", "Graphviz exceeded 30s.") from exc
    if code != 0 or not stdout.startswith(b"\x89PNG"):
        detail = stderr.decode("utf-8", errors="replace").split("\n", 1)[0][:300]
        raise CloudiatorError(400, "invalid_request_error", detail or "Graphviz could not render the diagram.", param="source")
    return stdout


async def _mermaid_or_graphviz(source: str) -> tuple[bytes, str]:
    """Any mermaid failure, including a missing binary, falls back to Graphviz."""
    try:
        png = await _mermaid(source)
    except Exception:  # noqa: BLE001 - missing mmdc, timeout, or Chromium crash
        return await _graphviz(source), "graphviz"
    if not png.startswith(b"\x89PNG"):
        return await _graphviz(source), "graphviz"
    return png, "mermaid"


async def _mermaid(source: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="cloudiator-mmd-") as directory:
        root = Path(directory)
        src = root / "diagram.mmd"
        out = root / "diagram.png"
        puppet = root / "puppeteer.json"
        src.write_text(source, encoding="utf-8")
        puppet.write_text(json.dumps({"args": _CHROMIUM_ARGS}), encoding="utf-8")
        _stdout, stderr, code = await run_group(
            ["mmdc", "-i", str(src), "-o", str(out), "-p", str(puppet), "-b", "white"],
            timeout=30,
        )
        if code != 0 or not out.is_file():
            raise CloudiatorError(400, "invalid_request_error", stderr.decode("utf-8", errors="replace")[:300])
        return out.read_bytes()
