"""A failed exclusive run still frees the lock and reloads the hot model."""

from __future__ import annotations

import asyncio

import pytest

from app.scheduler import STATE_IDLE, Scheduler
from app.system import PRESSURE_NORMAL


class _Models:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def unload_hot_model(self) -> None:
        self.calls.append("unload_hot")

    async def wait_until_only_embed_loaded(self, timeout: float = 30) -> None:
        self.calls.append("wait_only_embed")

    async def unload_all_generative(self) -> None:
        self.calls.append("unload_all_generative")

    async def reload_hot_model(self) -> None:
        self.calls.append("reload_hot")

    async def loaded_generative_models(self) -> list[str]:
        return ["qwen3.5:9b"]


class _Proc:
    def __init__(self) -> None:
        self.pid = 99
        self.returncode: int | None = None
        self.killed = False

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        while self.returncode is None:
            await asyncio.sleep(0.01)
        return self.returncode


def _scheduler(settings) -> tuple[Scheduler, _Models]:
    models = _Models()
    scheduler = Scheduler(settings, models)
    scheduler.pressure_level = PRESSURE_NORMAL
    scheduler._normal_polls = 5
    scheduler.free_disk_gb = 200.0
    return scheduler, models


async def test_a_raised_run_releases_the_lock_and_reloads_the_hot_model(settings):
    scheduler, models = _scheduler(settings)
    proc = _Proc()

    async def work():
        scheduler.subprocesses.register(proc)
        raise RuntimeError("mflux died")

    with pytest.raises(RuntimeError, match="mflux died"):
        await scheduler.run_exclusive("flux", work)

    assert "reload_hot" in models.calls
    assert models.calls[0] == "unload_hot"
    assert not scheduler.metal_lock.locked()
    assert scheduler.state == STATE_IDLE
    assert proc.returncode is not None
    assert proc not in scheduler.subprocesses._procs
