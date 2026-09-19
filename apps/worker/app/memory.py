"""Memory / disk / pressure snapshot. Off the request path (PLAN.md §4)."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from dataclasses import dataclass

from app.config import Settings

log = logging.getLogger("cloudiator.memory")

PRESSURE_NAMES = {1: "normal", 2: "warn", 4: "critical"}
# launchd EnvironmentVariables PATH replaces the default and often omits
# /usr/sbin, where macOS ships sysctl. Always exec the absolute binary.
_SYSCTL_CANDIDATES = ("/usr/sbin/sysctl", "/sbin/sysctl")


@dataclass
class MemorySnapshot:
    pressure: str = "normal"
    pressure_level: int = 1
    free_mb: int = 0
    free_disk_gb: float = 0.0
    swap_used: str = "unknown"
    ok: bool = True


class MemoryMonitor:
    def __init__(self) -> None:
        self.snapshot = MemorySnapshot()
        self._task: asyncio.Task[None] | None = None

    async def start(self, settings: Settings) -> None:
        try:
            await self.refresh(settings)
        except Exception as exc:
            log.warning("initial memory snapshot failed: %s", exc)
        self._task = asyncio.create_task(self._loop(settings), name="memory-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self, settings: Settings) -> None:
        while True:
            try:
                await self.refresh(settings)
            except Exception as exc:
                log.warning("memory poll failed: %s", exc)
            await asyncio.sleep(5)

    async def refresh(self, settings: Settings) -> MemorySnapshot:
        pressure_level, pressure = await self._pressure()
        free_mb = await self._free_mb()
        swap_used = await self._swap_used()
        disk = _free_disk_gb(settings)
        degraded = pressure != "normal" or disk < settings.min_free_disk_gb
        self.snapshot = MemorySnapshot(
            pressure=pressure,
            pressure_level=pressure_level,
            free_mb=free_mb,
            free_disk_gb=round(disk, 2),
            swap_used=swap_used,
            ok=not degraded,
        )
        return self.snapshot

    async def _pressure(self) -> tuple[int, str]:
        if sys.platform != "darwin":
            return 1, "normal"
        raw = await _sysctl_n("kern.memorystatus_vm_pressure_level")
        try:
            level = int(raw.strip())
        except (TypeError, ValueError):
            return 1, "normal"
        return level, PRESSURE_NAMES.get(level, "warn" if level > 1 else "normal")

    async def _free_mb(self) -> int:
        if sys.platform == "darwin":
            page_size = await _sysctl_n("hw.pagesize")
            free_pages = await _sysctl_n("vm.page_free_count")
            try:
                return int(page_size) * int(free_pages) // (1024 * 1024)
            except (TypeError, ValueError):
                return 0
        return _linux_mem_available_mb()

    async def _swap_used(self) -> str:
        if sys.platform != "darwin":
            return "n/a"
        raw = await _sysctl("vm.swapusage")
        return raw.strip() or "unknown"


def _sysctl_bin() -> str:
    for candidate in _SYSCTL_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("sysctl")
    return found or "/usr/sbin/sysctl"


async def _sysctl_n(name: str) -> str:
    return await _run(_sysctl_bin(), "-n", name)


async def _sysctl(name: str) -> str:
    return await _run(_sysctl_bin(), name)


async def _run(*args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        log.warning("missing executable: %s", args[0] if args else "?")
        return ""
    out, _err = await proc.communicate()
    return out.decode("utf-8", errors="replace")


def _linux_mem_available_mb() -> int:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except OSError:
        return 0
    return 0


def _free_disk_gb(settings: Settings) -> float:
    path = settings.artifact_dir
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = path.anchor or "/"
    usage = shutil.disk_usage(path)
    return usage.free / (1024**3)


monitor = MemoryMonitor()
