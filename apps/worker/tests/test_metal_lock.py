from __future__ import annotations

import asyncio

import pytest

from app.errors import ApiError
from app.scheduler import Scheduler, SchedulerState


@pytest.mark.asyncio
async def test_lock_released_when_body_raises() -> None:
    sched = Scheduler()

    async def boom() -> None:
        async with sched.acquire_metal(wait_seconds=1):
            raise RuntimeError("generation failed")

    with pytest.raises(RuntimeError, match="generation failed"):
        await boom()

    assert not sched.metal_lock.locked()
    assert sched.state == SchedulerState.idle_hot_9b


@pytest.mark.asyncio
async def test_wait_timeout_returns_metal_busy() -> None:
    sched = Scheduler()
    await sched.metal_lock.acquire()
    try:
        with pytest.raises(ApiError) as exc:
            async with sched.acquire_metal(wait_seconds=0.05):
                pass
        assert exc.value.code == "metal_busy"
        assert exc.value.status_code == 429
    finally:
        sched.metal_lock.release()
    assert not sched.metal_lock.locked()


@pytest.mark.asyncio
async def test_exclusive_finally_reloads_even_when_run_raises() -> None:
    sched = Scheduler()
    events: list[str] = []

    async def unload_hot() -> None:
        events.append("unload_hot")

    async def wait_embed() -> None:
        events.append("wait_embed")

    async def run() -> str:
        events.append("run")
        raise RuntimeError("mflux oom")

    async def kill_orphans() -> None:
        events.append("kill")

    async def unload_all() -> None:
        events.append("unload_all")

    async def reload_hot() -> None:
        events.append("reload")

    with pytest.raises(RuntimeError, match="mflux oom"):
        await sched.run_exclusive(
            "flux",
            run,
            unload_hot=unload_hot,
            wait_until_only_embed=wait_embed,
            kill_orphans=kill_orphans,
            unload_all_generative=unload_all,
            reload_hot=reload_hot,
            timeout=5,
        )

    assert events == ["unload_hot", "wait_embed", "run", "kill", "unload_all", "reload"]
    assert not sched.metal_lock.locked()
    assert sched.state == SchedulerState.idle_hot_9b
    assert sched.exclusive_running is False


@pytest.mark.asyncio
async def test_cpu_heavy_lock_is_capacity_one() -> None:
    sched = Scheduler()
    order: list[str] = []

    async def holder() -> None:
        async with sched.acquire_cpu_heavy("normal", wait_seconds=1):
            order.append("hold")
            await asyncio.sleep(0.05)
            order.append("release")

    async def waiter() -> None:
        async with sched.acquire_cpu_heavy("normal", wait_seconds=1):
            order.append("second")

    await asyncio.gather(holder(), waiter())
    assert order == ["hold", "release", "second"]


@pytest.mark.asyncio
async def test_cpu_heavy_refuses_when_pressure_not_normal() -> None:
    sched = Scheduler()
    with pytest.raises(ApiError) as exc:
        async with sched.acquire_cpu_heavy("warn"):
            pass
    assert exc.value.code == "metal_busy"
