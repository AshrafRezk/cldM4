"""Local FLUX.1-schnell. Weights are a directory on disk. Never a download.

The 24 GB Mini measurement: a 1024² generate without --low-ram peaked at
19.08 GB and used swap. With --low-ram the peak was 8.43 GB and swap did not
rise. --low-ram stays on unless MFLUX_LOW_RAM=false.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.errors import CloudiatorError

NAME = "flux_generate"
CAPABILITY = "image_generation"
TIMEOUT_SECONDS = 600
GPU = True

MAX_EDGE = 1024
MIN_EDGE = 256
MAX_STEPS = 4
MAX_PROMPT = 4_000
_PNG = b"\x89PNG"


def mflux_binary() -> str:
    found = shutil.which("mflux-generate")
    if found:
        return found
    home = os.path.expanduser("~/.local/bin/mflux-generate")
    for candidate in (home, "/opt/homebrew/bin/mflux-generate", "/usr/local/bin/mflux-generate"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError("mflux-generate")


def image_request(arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CloudiatorError(400, "invalid_request_error", "prompt is required.", param="prompt")
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT:
        raise CloudiatorError(400, "invalid_request_error", "prompt is too long.", param="prompt")
    width, height = _edge(arguments.get("width"), "width"), _edge(arguments.get("height"), "height")
    if "size" in arguments and arguments.get("size") not in (None, ""):
        width, height = _size(arguments.get("size"))
    steps = arguments.get("steps", MAX_STEPS)
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= MAX_STEPS:
        raise CloudiatorError(
            400, "invalid_request_error", f"steps must be 1..{MAX_STEPS}.", param="steps"
        )
    seed = arguments.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise CloudiatorError(400, "invalid_request_error", "seed must be an integer.", param="seed")
    return {
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "seed": seed,
    }


def mflux_command(settings, request: dict[str, Any], dest: str) -> list[str]:
    """The argv of one generate. The model argument is always a local directory."""
    model = settings.mflux_model_path
    if not model or not os.path.isdir(model):
        raise CloudiatorError(
            503,
            "not_supported",
            "MFLUX_MODEL_PATH is not a local directory. The worker will not download weights.",
            error_type="server_error",
        )
    try:
        binary = mflux_binary()
    except FileNotFoundError as exc:
        raise CloudiatorError(
            503,
            "not_supported",
            "mflux-generate is not installed. uv tool install mflux, then restart the worker.",
            error_type="server_error",
        ) from exc
    argv = [
        binary,
        "--model",
        model,
        "--base-model",
        "schnell",
        "--steps",
        str(request["steps"]),
        "--height",
        str(request["height"]),
        "--width",
        str(request["width"]),
        "--prompt",
        request["prompt"],
        "--output",
        dest,
    ]
    if settings.mflux_low_ram:
        argv.append("--low-ram")
    if request["seed"] is not None:
        argv.extend(["--seed", str(request["seed"])])
    if "--quantize" in argv or "huggingface.co" in model:
        raise CloudiatorError(
            400,
            "not_supported",
            "FLUX quantize and network model ids are not accepted.",
            param="model",
        )
    return argv


async def generate(arguments: dict[str, Any], *, settings, artifacts, scheduler=None) -> dict[str, Any]:
    request = image_request(arguments)
    handle = tempfile.NamedTemporaryFile(prefix="flux-", suffix=".png", delete=False)
    dest = handle.name
    handle.close()
    proc: asyncio.subprocess.Process | None = None
    try:
        argv = mflux_command(settings, request, dest)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if scheduler is not None:
            scheduler.subprocesses.register(proc)
        stdout, stderr = await proc.communicate()
        code = proc.returncode or 0
        png = Path(dest).read_bytes() if os.path.isfile(dest) else b""
        if code != 0 or not png.startswith(_PNG):
            detail = (stderr or stdout or b"").decode("utf-8", errors="replace").split("\n", 1)[0][:300]
            raise CloudiatorError(
                400,
                "invalid_request_error",
                detail or "mflux could not write a PNG.",
                param="prompt",
            )
        artifact_id = artifacts.save(png, ".png")
        return {"id": artifact_id, "url": artifacts.sign(artifact_id)}
    finally:
        if proc is not None and proc.returncode is not None and scheduler is not None:
            scheduler.subprocesses.forget(proc)
        try:
            os.unlink(dest)
        except OSError:
            pass


run = generate


def _edge(value: Any, name: str) -> int:
    if value is None:
        return MAX_EDGE
    if isinstance(value, bool) or not isinstance(value, int):
        raise CloudiatorError(400, "invalid_request_error", f"{name} must be an integer.", param=name)
    if value < MIN_EDGE or value > MAX_EDGE or value % 64 != 0:
        raise CloudiatorError(
            400,
            "invalid_request_error",
            f"{name} must be a multiple of 64 from {MIN_EDGE} to {MAX_EDGE}.",
            param=name,
        )
    return value


def _size(value: Any) -> tuple[int, int]:
    if not isinstance(value, str) or "x" not in value:
        raise CloudiatorError(400, "invalid_request_error", "size must look like 1024x1024.", param="size")
    raw_w, raw_h = value.lower().split("x", 1)
    try:
        width, height = int(raw_w), int(raw_h)
    except ValueError as exc:
        raise CloudiatorError(
            400, "invalid_request_error", "size must look like 1024x1024.", param="size"
        ) from exc
    return _edge(width, "width"), _edge(height, "height")
