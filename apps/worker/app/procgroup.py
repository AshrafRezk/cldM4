"""Run a subprocess in its own process group and kill the whole group.

mermaid-cli forks Chromium. Killing only the parent leaves the browser resident.
"""

from __future__ import annotations

import asyncio
import os
import signal


async def run_group(
    argv: list[str],
    *,
    timeout: float,
    stdin: bytes | None = None,
) -> tuple[bytes, bytes, int]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except TimeoutError:
        await kill_group(proc)
        raise
    return stdout, stderr, proc.returncode or 0


async def kill_group(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM the group, then SIGKILL if it is still alive."""
    if proc.returncode is not None or proc.pid is None:
        return
    _signal_group(proc.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
        return
    except TimeoutError:
        _signal_group(proc.pid, signal.SIGKILL)
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except TimeoutError:
        return


def _signal_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
