"""metal_lock and the exclusive-slot contract (PLAN.md §8).

The property that keeps the appliance alive unattended: after any failure the
lock is free and the hot model is back.
"""

from __future__ import annotations

import asyncio

import pytest

from app.errors import CloudiatorError
from app.scheduler import (
    REWARM_AFTER_SECONDS,
    STATE_IDLE,
    Scheduler,
)
from app.system import PRESSURE_CRITICAL, PRESSURE_NORMAL


class FakeModels:
    def __init__(self, *, loaded: list[str] | None = None) -> None:
        self.calls: list[str] = []
        self.loaded = ["qwen3.5:9b"] if loaded is None else list(loaded)
        self.reload_fails = False

    async def unload_hot_model(self) -> None:
        self.calls.append("unload_hot")
        self.loaded = [name for name in self.loaded if name == "nomic-embed-text"]

    async def wait_until_only_embed_loaded(self, timeout: float = 30) -> None:
        self.calls.append("wait_only_embed")

    async def unload_all_generative(self) -> None:
        self.calls.append("unload_all_generative")
        self.loaded = [name for name in self.loaded if name == "nomic-embed-text"]

    async def reload_hot_model(self) -> None:
        self.calls.append("reload_hot")
        if self.reload_fails:
            raise RuntimeError("ollama is down")
        if "qwen3.5:9b" not in self.loaded:
            self.loaded.append("qwen3.5:9b")

    async def loaded_models(self) -> list[str]:
        return list(self.loaded)

    async def loaded_generative_models(self) -> list[str]:
        return [name for name in self.loaded if name != "nomic-embed-text"]


class FakeProcess:
    def __init__(self, *, ignores_terminate: bool = False) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self._ignores_terminate = ignores_terminate

    def terminate(self) -> None:
        self.terminated = True
        if not self._ignores_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        while self.returncode is None:
            await asyncio.sleep(0.01)
        return self.returncode


def make_scheduler(settings, models: FakeModels | None = None) -> Scheduler:
    scheduler = Scheduler(settings, models or FakeModels())
    scheduler.pressure_level = PRESSURE_NORMAL
    scheduler._normal_polls = 5
    scheduler.free_disk_gb = 200.0
    return scheduler


async def test_chat_slot_releases_when_the_body_raises(settings):
    scheduler = make_scheduler(settings)

    with pytest.raises(RuntimeError):
        async with scheduler.chat_slot():
            assert scheduler.metal_lock.locked()
            raise RuntimeError("generation blew up")

    assert not scheduler.metal_lock.locked()
    assert scheduler.state == STATE_IDLE
    assert scheduler.metal_queue_depth == 0


async def test_chat_slot_releases_on_cancellation(settings):
    scheduler = make_scheduler(settings)
    entered = asyncio.Event()

    async def holder():
        async with scheduler.chat_slot():
            entered.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(holder())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not scheduler.metal_lock.locked()


async def test_chat_slot_returns_metal_busy_instead_of_queueing(settings):
    scheduler = make_scheduler(settings)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with scheduler.chat_slot():
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()

    with pytest.raises(CloudiatorError) as caught:
        async with scheduler.chat_slot(wait_seconds=0.05):
            pass

    assert caught.value.status_code == 429
    assert caught.value.code == "metal_busy"
    assert caught.value.retry_after == 5
    assert caught.value.param == "POST /v1/jobs"
    assert scheduler.metal_queue_depth == 0

    release.set()
    await task
    assert not scheduler.metal_lock.locked()


async def test_run_exclusive_happy_path_order(settings):
    models = FakeModels()
    scheduler = make_scheduler(settings, models)

    async def work():
        assert scheduler.state == "exclusive_flux"
        return "image.png"

    assert await scheduler.run_exclusive("flux", work) == "image.png"
    assert models.calls == [
        "unload_hot",
        "wait_only_embed",
        "unload_all_generative",
        "reload_hot",
    ]
    assert scheduler.state == STATE_IDLE
    assert not scheduler.metal_lock.locked()


async def test_run_exclusive_reloads_hot_model_when_work_raises(settings):
    models = FakeModels()
    scheduler = make_scheduler(settings, models)

    async def work():
        raise RuntimeError("mflux was OOM-killed")

    with pytest.raises(RuntimeError):
        await scheduler.run_exclusive("flux", work)

    assert "reload_hot" in models.calls
    assert "qwen3.5:9b" in models.loaded
    assert not scheduler.metal_lock.locked()
    assert scheduler.state == STATE_IDLE


async def test_run_exclusive_kills_orphan_subprocess(settings):
    scheduler = make_scheduler(settings)
    proc = FakeProcess(ignores_terminate=True)
    scheduler.subprocesses.register(proc)

    async def work():
        raise RuntimeError("hung")

    with pytest.raises(RuntimeError):
        await scheduler.run_exclusive("whisper", work)

    assert proc.terminated
    assert proc.killed


async def test_run_exclusive_survives_a_failed_reload(settings):
    models = FakeModels()
    models.reload_fails = True
    scheduler = make_scheduler(settings, models)

    async def work():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await scheduler.run_exclusive("20b", work)

    assert "hot_model_missing" in scheduler.degraded
    assert not scheduler.metal_lock.locked()


async def test_exclusive_is_shed_under_memory_pressure(settings):
    scheduler = make_scheduler(settings)
    scheduler.pressure_level = PRESSURE_CRITICAL
    scheduler._normal_polls = 0

    async def work():
        raise AssertionError("must not run under pressure")

    with pytest.raises(CloudiatorError) as caught:
        await scheduler.run_exclusive("flux", work)

    assert caught.value.status_code == 429
    assert not scheduler.metal_lock.locked()


async def test_recovery_needs_two_consecutive_normal_polls(settings):
    scheduler = make_scheduler(settings)
    scheduler.pressure_level = PRESSURE_NORMAL
    scheduler._normal_polls = 1
    assert not scheduler.pressure_ok
    scheduler._normal_polls = 2
    assert scheduler.pressure_ok


async def test_a_fresh_scheduler_is_not_shedding_before_the_first_poll(settings):
    """The recovery rule must not make the worker refuse work at boot."""
    scheduler = Scheduler(settings, FakeModels())

    assert scheduler.pressure_ok
    assert scheduler.allow_exclusive()
    assert scheduler.state == STATE_IDLE


async def test_cpu_heavy_lock_is_separate_from_metal_lock(settings):
    scheduler = make_scheduler(settings)

    async with scheduler.chat_slot():
        async with scheduler.cpu_heavy_slot():
            assert scheduler.metal_lock.locked()
            assert scheduler.cpu_heavy_lock.locked()

    assert not scheduler.metal_lock.locked()
    assert not scheduler.cpu_heavy_lock.locked()


async def test_cpu_heavy_is_refused_while_an_exclusive_model_holds_the_slot(settings):
    scheduler = make_scheduler(settings)
    reached = asyncio.Event()

    async def work():
        with pytest.raises(CloudiatorError):
            async with scheduler.cpu_heavy_slot():
                pass
        reached.set()

    await scheduler.run_exclusive("flux", work)
    assert reached.is_set()


async def test_two_generative_models_is_a_p0_and_blocks_exclusive_work(settings):
    models = FakeModels(loaded=["qwen3.5:9b", "gpt-oss:20b", "nomic-embed-text"])
    scheduler = make_scheduler(settings, models)

    await scheduler._refresh_loaded()

    assert "two_generative_models" in scheduler.degraded
    assert not scheduler.allow_exclusive()


async def test_embedder_beside_one_generative_model_is_expected(settings):
    models = FakeModels(loaded=["qwen3.5:9b", "nomic-embed-text"])
    scheduler = make_scheduler(settings, models)

    await scheduler._refresh_loaded()

    assert scheduler.degraded == {}
    assert scheduler.allow_exclusive()


async def test_watchdog_rewarms_the_hot_model_after_an_oom_kill(settings):
    models = FakeModels(loaded=["nomic-embed-text"])
    scheduler = make_scheduler(settings, models)

    await scheduler.watchdog_once(elapsed=REWARM_AFTER_SECONDS / 2)
    assert "reload_hot" not in models.calls

    await scheduler.watchdog_once(elapsed=REWARM_AFTER_SECONDS / 2)
    assert "reload_hot" in models.calls
    assert "qwen3.5:9b" in models.loaded


async def test_watchdog_does_not_interfere_with_exclusive_work(settings):
    models = FakeModels(loaded=["nomic-embed-text"])
    scheduler = make_scheduler(settings, models)
    scheduler._exclusive_held = True

    await scheduler.watchdog_once(elapsed=REWARM_AFTER_SECONDS * 2)

    assert "reload_hot" not in models.calls
