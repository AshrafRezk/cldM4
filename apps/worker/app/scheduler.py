"""RAM scheduler (PLAN.md §8).

One `metal_lock` for the single Metal slot, a separate `cpu_heavy_lock` for
Chromium-backed renderers and big CPU work, and a state machine. The scheduler
is in-process state, which is why the single-process gate is not optional.

The crash path is the point of this module. If an exclusive model is
OOM-killed, raises, or hangs and the reload is not in a `finally`, the lock is
held forever and the hot model is gone: every later call gets a 429 until a
human reboots the Mini.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any, Awaitable, Callable

from .errors import CloudiatorError, metal_busy
from .system import (
    PRESSURE_NORMAL,
    free_disk_gb,
    pressure_name,
    read_free_mb,
    read_pressure_level,
    read_swap_used_mb,
)

log = logging.getLogger("cloudiator.scheduler")

STATE_IDLE = "idle_hot_9b"
STATE_LOADING = "loading"
STATE_CHAT = "chat_9b"
STATE_PRESSURE_SHED = "pressure_shed"
EXCLUSIVE_KINDS = ("20b", "flux", "whisper")

POLL_SECONDS = 5.0
WATCHDOG_SECONDS = 30.0
REWARM_AFTER_SECONDS = 60.0
NORMAL_POLLS_TO_RECOVER = 2
SUBPROCESS_GRACE_SECONDS = 5.0


class SubprocessRegistry:
    """Tracks exclusive-slot subprocesses (mflux, whisper) so a hung one dies.

    A hung mflux holding 12 GB is worse than a failed job.
    """

    def __init__(self) -> None:
        self._procs: set[Any] = set()

    def register(self, proc: Any) -> None:
        self._procs.add(proc)

    def forget(self, proc: Any) -> None:
        self._procs.discard(proc)

    async def kill_all(self) -> None:
        for proc in list(self._procs):
            await self._kill(proc)
            self._procs.discard(proc)

    async def _kill(self, proc: Any) -> None:
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
        except (ProcessLookupError, OSError):
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=SUBPROCESS_GRACE_SECONDS)
            return
        except asyncio.TimeoutError:
            log.warning("subprocess %s ignored terminate(); killing", getattr(proc, "pid", "?"))
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=SUBPROCESS_GRACE_SECONDS)
        except asyncio.TimeoutError:
            log.error("subprocess %s survived kill()", getattr(proc, "pid", "?"))


class Scheduler:
    def __init__(self, settings, models) -> None:
        self.settings = settings
        self.models = models
        self.metal_lock = asyncio.Lock()
        self.cpu_heavy_lock = asyncio.Semaphore(1)
        self.subprocesses = SubprocessRegistry()

        self.state = STATE_IDLE
        self.metal_queue_depth = 0

        self.pressure_level: int | None = None
        self.swap_used_mb: float | None = None
        self.free_mb: int | None = None
        self.free_disk_gb: float | None = None
        self.loaded: list[str] = []
        self.degraded: dict[str, str] = {}

        # Starts satisfied: the two-consecutive-normal rule exists to make
        # recovery from warn/critical deliberate, not to shed work at boot.
        self._normal_polls = NORMAL_POLLS_TO_RECOVER
        self._exclusive_held = False
        self._seconds_without_generative = 0.0
        self._tasks: list[asyncio.Task] = []

    # ---- derived state ----------------------------------------------------

    @property
    def pressure_ok(self) -> bool:
        """Unknown pressure is treated as usable; the Mini reports it, Linux does not."""
        if self.pressure_level is None:
            return True
        return self.pressure_level == PRESSURE_NORMAL and self._normal_polls >= NORMAL_POLLS_TO_RECOVER

    @property
    def disk_ok(self) -> bool:
        if self.free_disk_gb is None:
            return True
        return self.free_disk_gb >= self.settings.min_free_disk_gb

    @property
    def disk_hard_stop(self) -> bool:
        if self.free_disk_gb is None:
            return False
        return self.free_disk_gb < self.settings.hard_free_disk_gb

    def allow_exclusive(self) -> bool:
        return self.pressure_ok and self.disk_ok and "two_generative_models" not in self.degraded

    def allow_cpu_heavy(self) -> bool:
        return self.pressure_ok and not self._exclusive_held

    def mark_degraded(self, reason: str, message: str) -> None:
        if reason not in self.degraded:
            log.error("health degraded (%s): %s", reason, message)
        self.degraded[reason] = message

    def clear_degraded(self, reason: str) -> None:
        self.degraded.pop(reason, None)

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "pressure": pressure_name(self.pressure_level),
            "swap_used_mb": self.swap_used_mb,
            "free_mb": self.free_mb,
            "free_disk_gb": None if self.free_disk_gb is None else round(self.free_disk_gb, 1),
            "loaded": list(self.loaded),
            "queue_depth": self.metal_queue_depth,
            "degraded": sorted(self.degraded),
        }

    # ---- Metal slot -------------------------------------------------------

    @asynccontextmanager
    async def chat_slot(self, *, wait_seconds: float | None = None):
        """Hold the Metal slot for a sync chat call.

        A wait longer than the budget is a 429 with Retry-After, not a queue:
        the caller's 120s Apex timeout is already ticking (PLAN.md §8 rule 5).
        """
        timeout = self.settings.metal_wait_seconds if wait_seconds is None else wait_seconds
        self.metal_queue_depth += 1
        try:
            try:
                await asyncio.wait_for(self.metal_lock.acquire(), timeout=timeout)
            except asyncio.TimeoutError:
                raise metal_busy() from None
        finally:
            self.metal_queue_depth -= 1

        self.state = STATE_CHAT
        try:
            yield
        finally:
            self.state = STATE_IDLE if self.pressure_ok else STATE_PRESSURE_SHED
            self.metal_lock.release()

    async def run_exclusive(self, kind: str, run: Callable[[], Awaitable[Any]]) -> Any:
        """Unload the hot model, verify, run, then always put the hot model back."""
        if kind not in EXCLUSIVE_KINDS:
            raise ValueError(f"unknown exclusive kind {kind!r}")
        if not self.allow_exclusive():
            raise CloudiatorError(
                429,
                "metal_busy",
                f"Exclusive work is shed: pressure={pressure_name(self.pressure_level)}, "
                f"free_disk_gb={self.free_disk_gb}.",
                error_type="rate_limit_error",
                retry_after=30,
            )

        async with self.metal_lock:
            self._exclusive_held = True
            try:
                self.state = STATE_LOADING
                await self.models.unload_hot_model()
                await self.models.wait_until_only_embed_loaded(timeout=30)
                self.state = f"exclusive_{kind}"
                return await asyncio.wait_for(
                    run(), timeout=self.settings.exclusive_timeout_seconds
                )
            finally:
                await self._restore_hot_model()
                self._exclusive_held = False
                self.state = STATE_IDLE if self.pressure_ok else STATE_PRESSURE_SHED

    async def _restore_hot_model(self) -> None:
        """Best effort, never raises: a raise here would mask the real error."""
        try:
            await self.subprocesses.kill_all()
        except Exception:  # noqa: BLE001 - cleanup must not raise
            log.exception("failed to kill exclusive-slot subprocesses")
        try:
            await self.models.unload_all_generative()
        except Exception:  # noqa: BLE001
            log.exception("failed to unload generative models")
        try:
            await self.models.reload_hot_model()
            self.clear_degraded("hot_model_missing")
        except Exception:  # noqa: BLE001
            self.mark_degraded(
                "hot_model_missing",
                "could not reload the hot model after exclusive work; watchdog will retry",
            )

    @asynccontextmanager
    async def cpu_heavy_slot(self):
        """Chromium renderers and big CPU work. Does not take metal_lock."""
        if not self.allow_cpu_heavy():
            raise CloudiatorError(
                429,
                "metal_busy",
                "CPU-heavy work is shed while memory pressure is not normal or an exclusive "
                "model holds the Metal slot.",
                error_type="rate_limit_error",
                retry_after=15,
            )
        await self.cpu_heavy_lock.acquire()
        try:
            yield
        finally:
            self.cpu_heavy_lock.release()

    # ---- background tasks -------------------------------------------------

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._pressure_loop(), name="pressure-poller"),
            asyncio.create_task(self._watchdog_loop(), name="hot-model-watchdog"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def poll_once(self) -> None:
        self.pressure_level = await read_pressure_level()
        self.swap_used_mb = await read_swap_used_mb()
        self.free_mb = await read_free_mb()
        self.free_disk_gb = free_disk_gb(self.settings.artifact_dir) or free_disk_gb("/")

        if self.pressure_level in (None, PRESSURE_NORMAL):
            self._normal_polls += 1
        else:
            self._normal_polls = 0

        if self.swap_used_mb:
            self.mark_degraded(
                "swap_in_use",
                f"{self.swap_used_mb:.0f} MB of swap in use; reduce the configuration "
                "(PLAN.md §4)",
            )
        else:
            self.clear_degraded("swap_in_use")

        if self.disk_hard_stop:
            self.mark_degraded(
                "disk_critical",
                f"{self.free_disk_gb:.1f} GB free is below the {self.settings.hard_free_disk_gb} "
                "GB hard floor",
            )
        elif not self.disk_ok:
            self.mark_degraded(
                "disk_low",
                f"{self.free_disk_gb:.1f} GB free is below MIN_FREE_DISK_GB="
                f"{self.settings.min_free_disk_gb}",
            )
        else:
            self.clear_degraded("disk_low")
            self.clear_degraded("disk_critical")

        await self._refresh_loaded()
        self._update_pressure_state()

    async def _refresh_loaded(self) -> None:
        try:
            self.loaded = await self.models.loaded_models()
            self.clear_degraded("ollama_unreachable")
        except Exception:  # noqa: BLE001 - poller must not die on a dead Ollama
            self.loaded = []
            self.mark_degraded("ollama_unreachable", f"no answer from {self.settings.ollama_host}")
            return

        embed = self.settings.embed_model.removesuffix(":latest")
        generative = [name for name in self.loaded if name and name != embed]
        if len(generative) >= 2:
            self.mark_degraded(
                "two_generative_models",
                f"P0: {generative} are both resident; exclusive work is refused (PLAN.md §4)",
            )
        else:
            self.clear_degraded("two_generative_models")

    def _update_pressure_state(self) -> None:
        if self.state in (STATE_IDLE, STATE_PRESSURE_SHED):
            self.state = STATE_IDLE if self.pressure_ok else STATE_PRESSURE_SHED

    async def _pressure_loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("pressure poll failed")
            await asyncio.sleep(POLL_SECONDS)

    async def _watchdog_loop(self) -> None:
        """Re-warm the hot model after an OOM kill (PLAN.md §8)."""
        while True:
            await asyncio.sleep(WATCHDOG_SECONDS)
            try:
                await self.watchdog_once(elapsed=WATCHDOG_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("watchdog pass failed")

    async def watchdog_once(self, *, elapsed: float) -> None:
        if self._exclusive_held:
            self._seconds_without_generative = 0.0
            return
        try:
            generative = await self.models.loaded_generative_models()
        except Exception:  # noqa: BLE001
            return
        if generative:
            self._seconds_without_generative = 0.0
            self.clear_degraded("hot_model_missing")
            return

        self._seconds_without_generative += elapsed
        if self._seconds_without_generative < REWARM_AFTER_SECONDS:
            return
        log.warning("no generative model resident for %.0fs; re-warming the hot model",
                    self._seconds_without_generative)
        try:
            await self.models.reload_hot_model()
            self._seconds_without_generative = 0.0
            self.clear_degraded("hot_model_missing")
        except Exception:  # noqa: BLE001
            self.mark_degraded("hot_model_missing", "watchdog could not re-warm the hot model")
