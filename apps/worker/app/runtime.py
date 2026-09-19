"""Boot gates: arm64, single worker, OLLAMA_MAX_LOADED_MODELS=2, pidfile."""

from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path

from app.config import Settings

log = logging.getLogger("cloudiator.runtime")


class BootError(SystemExit):
    pass


def _is_test(settings: Settings) -> bool:
    return settings.cloudiator_env.lower() == "test"


def assert_architecture(settings: Settings) -> None:
    """Abort on Rosetta / x86_64. Test env is allowed to run on Linux CI."""
    if _is_test(settings):
        return
    machine = platform.machine().lower()
    if machine not in ("arm64", "aarch64"):
        raise BootError(
            f"abort: platform.machine()={machine!r}; Cloudiator requires arm64 "
            "(Rosetta/x86_64 Python breaks Vision and MLX). See PLAN.md §5."
        )
    py_machine = platform.machine().lower()
    if py_machine not in ("arm64", "aarch64"):
        raise BootError(f"abort: Python is {py_machine}, not arm64")
    if sys.platform != "darwin":
        raise BootError(
            f"abort: production worker must run on macOS Darwin, not {sys.platform}. "
            "This Cloud/Linux host can run tests with CLOUDIATOR_ENV=test only."
        )


def assert_web_concurrency() -> None:
    raw = os.environ.get("WEB_CONCURRENCY", "1").strip() or "1"
    if raw != "1":
        raise BootError(
            f"refuse to boot: WEB_CONCURRENCY={raw!r}. metal_lock is in-process; "
            "uvicorn --workers must be 1 (PLAN.md §6)."
        )


def assert_ollama_slots(settings: Settings) -> None:
    raw = os.environ.get("OLLAMA_MAX_LOADED_MODELS")
    if raw is None:
        if _is_test(settings):
            return
        raise BootError(
            "refuse to boot: OLLAMA_MAX_LOADED_MODELS is unset. "
            "It must be 2 (slot 1 = one generative model, slot 2 = nomic-embed-text only)."
        )
    if raw.strip() != "2":
        raise BootError(
            f"refuse to boot: OLLAMA_MAX_LOADED_MODELS={raw!r}; required value is 2 "
            "(PLAN.md §4). Do not raise it to 'fix' embeddings."
        )
    if settings.ollama_max_loaded_models != 2:
        raise BootError("refuse to boot: settings.ollama_max_loaded_models must be 2")


def acquire_pidfile(settings: Settings) -> None:
    if _is_test(settings):
        return
    path: Path = settings.pid_file
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            old = int(path.read_text().strip())
        except ValueError:
            old = None
        if old and _pid_is_alive(old) and old != os.getpid():
            raise BootError(
                f"refuse to boot: another worker pid {old} holds {path}. "
                "Two processes means two metal_lock schedulers."
            )
    path.write_text(str(os.getpid()))


def release_pidfile(settings: Settings) -> None:
    if _is_test(settings):
        return
    path: Path = settings.pid_file
    try:
        if path.exists() and path.read_text().strip() == str(os.getpid()):
            path.unlink()
    except OSError as exc:
        log.warning("pidfile release failed: %s", exc)


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def assert_runtime(settings: Settings) -> None:
    assert_web_concurrency()
    assert_architecture(settings)
    assert_ollama_slots(settings)
    acquire_pidfile(settings)
    log.info(
        "runtime ok env=%s python=%s machine=%s",
        settings.cloudiator_env,
        sys.version.split()[0],
        platform.machine(),
    )
