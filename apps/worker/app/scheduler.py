"""RAM scheduler: metal_lock + cpu_heavy_lock + state machine (PLAN.md §8)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from enum import Enum
from typing import TypeVar

from app.config import get_settings
from app.errors import metal_busy

log = logging.getLogger("cloudiator.scheduler")

T = TypeVar("T")


class SchedulerState(str, Enum):
    idle_hot_9b = "idle_hot_9b"
    loading = "loading"
    chat_9b = "chat_9b"
    exclusive_20b = "exclusive_20b"
    exclusive_flux = "exclusive_flux"
    exclusive_whisper = "exclusive_whisper"
    pressure_shed = "pressure_shed"


class Scheduler:
    def __init__(self) -> None:
        self.metal_lock = asyncio.Lock()
        self.cpu_heavy_lock = asyncio.Semaphore(1)
        self.state = SchedulerState.idle_hot_9b
        self.exclusive_running = False

    @asynccontextmanager
    async def acquire_metal(self, wait_seconds: float | None = None):
        settings = get_settings()
        timeout = settings.metal_lock_wait_seconds if wait_seconds is None else wait_seconds
        try:
            await asyncio.wait_for(self.metal_lock.acquire(), timeout=timeout)
        except TimeoutError as exc:
            raise metal_busy() from exc
        previous = self.state
        self.state = SchedulerState.chat_9b
        try:
            yield
        finally:
            self.state = (
                SchedulerState.idle_hot_9b
                if previous in {SchedulerState.idle_hot_9b, SchedulerState.chat_9b}
                else previous
            )
            self.metal_lock.release()

    @asynccontextmanager
    async def acquire_cpu_heavy(self, pressure: str, wait_seconds: float = 2.0):
        """Chromium/DuckDB/OpenCV. Separate from Metal; still refuses under pressure."""
        if pressure != "normal":
            raise metal_busy()
        if self.exclusive_running:
            raise metal_busy()
        try:
            await asyncio.wait_for(self.cpu_heavy_lock.acquire(), timeout=wait_seconds)
        except TimeoutError as exc:
            raise metal_busy() from exc
        try:
            yield
        finally:
            self.cpu_heavy_lock.release()

    async def run_exclusive(
        self,
        kind: str,
        run: Callable[[], Awaitable[T]],
        *,
        unload_hot: Callable[[], Awaitable[None]],
        wait_until_only_embed: Callable[[], Awaitable[None]],
        kill_orphans: Callable[[], Awaitable[None]],
        unload_all_generative: Callable[[], Awaitable[None]],
        reload_hot: Callable[[], Awaitable[None]],
        timeout: float,
    ) -> T:
        """Crash-safe exclusive slot. Phase E uses this; Phase A ships the contract."""
        state_map = {
            "20b": SchedulerState.exclusive_20b,
            "flux": SchedulerState.exclusive_flux,
            "whisper": SchedulerState.exclusive_whisper,
        }
        exclusive_state = state_map.get(kind, SchedulerState.exclusive_20b)
        async with self.metal_lock:
            self.exclusive_running = True
            self.state = SchedulerState.loading
            try:
                await unload_hot()
                await wait_until_only_embed()
                self.state = exclusive_state
                return await asyncio.wait_for(run(), timeout=timeout)
            finally:
                try:
                    await kill_orphans()
                except Exception as exc:
                    log.warning("kill_orphans failed: %s", exc)
                try:
                    await unload_all_generative()
                except Exception as exc:
                    log.warning("unload_all_generative failed: %s", exc)
                try:
                    await reload_hot()
                except Exception as exc:
                    log.error("reload_hot failed: %s", exc)
                self.exclusive_running = False
                self.state = SchedulerState.idle_hot_9b


scheduler = Scheduler()
