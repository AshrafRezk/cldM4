"""macOS memory, swap, and disk probes.

Every probe is async and every probe returns None instead of raising: these run
on a 5s poller, and a failed `sysctl` must degrade health rather than take the
worker down. Nothing here is ever called from a request path (PLAN.md §4) —
requests read the cached snapshot the poller writes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil

log = logging.getLogger("cloudiator.system")

PRESSURE_NORMAL = 1
PRESSURE_WARN = 2
PRESSURE_CRITICAL = 4

PRESSURE_NAMES = {
    PRESSURE_NORMAL: "normal",
    PRESSURE_WARN: "warn",
    PRESSURE_CRITICAL: "critical",
}

_SWAP_USED = re.compile(r"used\s*=\s*([0-9.]+)([KMG])")
_VM_STAT_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
_VM_STAT_ROW = re.compile(r"^(.*?):\s+(\d+)\.?$")


def pressure_name(level: int | None) -> str:
    if level is None:
        return "unknown"
    return PRESSURE_NAMES.get(level, f"level_{level}")


async def _run(*argv: str, timeout: float = 3.0) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode(errors="replace")


async def read_pressure_level() -> int | None:
    """1 = normal, 2 = warn, 4 = critical."""
    out = await _run("sysctl", "-n", "kern.memorystatus_vm_pressure_level")
    if out is None:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


async def read_swap_used_mb() -> float | None:
    out = await _run("sysctl", "-n", "vm.swapusage")
    if out is None:
        return None
    match = _SWAP_USED.search(out)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "K":
        return value / 1024
    if unit == "G":
        return value * 1024
    return value


async def read_free_mb() -> int | None:
    """Reclaimable memory estimate: free + inactive + speculative pages."""
    out = await _run("vm_stat")
    if out is None:
        return None
    page_size_match = _VM_STAT_PAGE_SIZE.search(out)
    page_size = int(page_size_match.group(1)) if page_size_match else 4096

    pages: dict[str, int] = {}
    for line in out.splitlines():
        row = _VM_STAT_ROW.match(line.strip())
        if row:
            pages[row.group(1).strip().lower()] = int(row.group(2))

    wanted = ("pages free", "pages inactive", "pages speculative")
    if not any(key in pages for key in wanted):
        return None
    total_pages = sum(pages.get(key, 0) for key in wanted)
    return int(total_pages * page_size / (1024 * 1024))


def free_disk_gb(path: str) -> float | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.free / (1024**3)
