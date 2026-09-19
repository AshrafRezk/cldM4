from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.memory import MemoryMonitor, _run, _sysctl_bin


@pytest.mark.asyncio
async def test_run_missing_binary_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    assert await _run("/usr/sbin/sysctl", "-n", "hw.ncpu") == ""


@pytest.mark.asyncio
async def test_start_survives_refresh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mon = MemoryMonitor()

    async def boom(_settings: object) -> None:
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(mon, "refresh", boom)
    await mon.start(get_settings())
    assert mon._task is not None
    await mon.stop()
    assert mon._task is None


@pytest.mark.asyncio
async def test_darwin_pressure_without_sysctl_is_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.memory.sys.platform", "darwin")

    async def boom(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    mon = MemoryMonitor()
    level, name = await mon._pressure()
    assert (level, name) == (1, "normal")


def test_sysctl_bin_prefers_usr_sbin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.memory.os.path.isfile", lambda path: path == "/usr/sbin/sysctl")
    monkeypatch.setattr("app.memory.os.access", lambda path, _mode: path == "/usr/sbin/sysctl")
    assert _sysctl_bin() == "/usr/sbin/sysctl"
