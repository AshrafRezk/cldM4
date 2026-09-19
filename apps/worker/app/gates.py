"""Boot gates.

These refuse to start the worker rather than run it in a configuration where
the RAM discipline in PLAN.md §§4, 6, 8 is silently void. Each one has a known
failure it prevents:

* not arm64 / not Python 3.11 — pyobjc Vision and MLX are broken or CPU-only
  under Rosetta, and the symptom appears in Phase D as "OCR is mysteriously
  broken" rather than an honest error (PLAN.md §5).
* more than one process — `metal_lock` is an in-process asyncio.Lock. Two
  workers means two schedulers, each convinced it owns Metal (PLAN.md §6).
* OLLAMA_MAX_LOADED_MODELS != 2 — slot 1 is one generative model, slot 2 is
  the embedder. A higher limit puts 9B + 20B resident and the box swaps
  (PLAN.md §4).
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import sys

log = logging.getLogger("cloudiator.gates")

REQUIRED_PYTHON = (3, 11)
UVICORN_PATTERN = "uvicorn app.main:app"


class BootRefused(RuntimeError):
    """Raised when a boot gate fails. The worker must not serve traffic."""


async def _sysctl_int(name: str) -> int | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "sysctl",
            "-n",
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2)
    except (OSError, asyncio.TimeoutError):
        return None
    try:
        return int(stdout.decode().strip())
    except ValueError:
        return None


async def assert_arm64_python311() -> None:
    if sys.version_info[:2] != REQUIRED_PYTHON:
        raise BootRefused(
            f"Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]} is required, this interpreter is "
            f"{sys.version_info.major}.{sys.version_info.minor}. Rebuild the venv: "
            "uv venv --python /opt/homebrew/opt/python@3.11/bin/python3.11"
        )

    system = platform.system()
    machine = platform.machine()
    if system != "Darwin":
        raise BootRefused(
            f"This worker runs on macOS on the Mac Mini only, detected {system}/{machine}. "
            "Metal, Apple Vision, and the LaunchAgents do not exist elsewhere (PLAN.md §0)."
        )
    if machine != "arm64":
        translated = await _sysctl_int("sysctl.proc_translated")
        hint = (
            " This process is running under Rosetta."
            if translated == 1
            else " Check that Terminal and Homebrew are not x86_64."
        )
        raise BootRefused(
            f"arm64 is required, detected {machine}.{hint} "
            "Abort the phase rather than continuing (PLAN.md §5)."
        )


def assert_single_process_config(settings) -> None:
    if settings.web_concurrency is not None and settings.web_concurrency != "1":
        raise BootRefused(
            f"WEB_CONCURRENCY={settings.web_concurrency!r} — only '1' is allowed. metal_lock is "
            "in-process, so a second worker is a second scheduler (PLAN.md §6)."
        )
    argv = sys.argv
    for index, arg in enumerate(argv):
        value: str | None = None
        if arg == "--workers" and index + 1 < len(argv):
            value = argv[index + 1]
        elif arg.startswith("--workers="):
            value = arg.split("=", 1)[1]
        if value is not None and value != "1":
            raise BootRefused(
                f"--workers {value} — only 1 is allowed (PLAN.md §6)."
            )
    if "--reload" in argv:
        raise BootRefused(
            "--reload spawns a reloader parent and a child; the LaunchAgent must never use it."
        )


async def assert_no_sibling_worker(*, settle_seconds: float = 3.0) -> None:
    """Refuse to boot beside another worker.

    A LaunchAgent restart can briefly overlap with the process it replaces, so
    wait for the predecessor to exit before treating it as a second scheduler.
    """
    deadline = asyncio.get_running_loop().time() + settle_seconds
    siblings: list[int] = []
    while True:
        siblings = await _find_sibling_pids()
        if not siblings or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.25)

    if siblings:
        raise BootRefused(
            f"Another worker is already running (pids {siblings}). metal_lock does not span "
            "processes; stop the other one first: launchctl bootout gui/$UID/ai.cloudiator.worker"
        )


async def _find_sibling_pids() -> list[int]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "pgrep",
            "-f",
            UVICORN_PATTERN,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
    except (OSError, asyncio.TimeoutError):
        log.warning("pgrep unavailable; cannot verify single-process invariant")
        return []

    mine = {os.getpid(), os.getppid()}
    pids: list[int] = []
    for line in stdout.decode().split():
        try:
            pid = int(line)
        except ValueError:
            continue
        if pid not in mine:
            pids.append(pid)
    return pids


def assert_ollama_two_slots(settings) -> None:
    value = settings.ollama_max_loaded_models
    if value != "2":
        raise BootRefused(
            f"OLLAMA_MAX_LOADED_MODELS={value!r} — must be exactly '2' (slot 1 = one generative "
            "model, slot 2 = the embedder). Set it on the Ollama LaunchAgent and in the worker "
            "environment so this assertion means something (PLAN.md §4)."
        )


async def run_boot_gates(settings) -> None:
    await assert_arm64_python311()
    assert_single_process_config(settings)
    assert_ollama_two_slots(settings)
    await assert_no_sibling_worker()
    log.info(
        "boot gates passed: arm64 macOS, python 3.11, single process, OLLAMA_MAX_LOADED_MODELS=2"
    )
