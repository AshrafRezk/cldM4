"""Opt-in capture of what a caller's browser sent, for tuning speech pickup.

Off unless VOICE_DEBUG_AUDIO=true. With it on, the call page uploads the
whole listening window (not only what its speech detector kept) plus the
detector's numbers, and each answer is saved on the Mini as a WAV and a JSON
note with what whisper heard. Files older than 24 hours are deleted on every
save. Nothing leaves the Mini; callers' audio is personal data, so turn this
off again once tuning is done.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

RETENTION_SECONDS = 24 * 3600


def _root(settings) -> Path:
    return Path(os.path.expanduser(settings.voice_debug_dir))


def purge(settings, now: float | None = None) -> int:
    root = _root(settings)
    if not root.is_dir():
        return 0
    cutoff = (now or time.time()) - RETENTION_SECONDS
    removed = 0
    for path in root.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def save(settings, *, call_sid: str, step: str, attempt: int, turn: int | None, language: str,
         audio: bytes, diag: dict[str, Any] | None) -> Path:
    """Write the window audio and a JSON note; returns the note's path."""
    root = _root(settings)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    purge(settings)
    stem = f"{time.strftime('%Y%m%d-%H%M%S')}_{call_sid[:14]}_{step}_t{turn if turn is not None else 0}a{attempt}"
    wav = root / f"{stem}.wav"
    wav.write_bytes(audio)
    note = root / f"{stem}.json"
    note.write_text(json.dumps({"call": call_sid, "step": step, "attempt": attempt, "turn": turn,
                                "language": language, "bytes": len(audio), "diag": diag or {}},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    for path in (wav, note):
        os.chmod(path, 0o600)
    return note


def record_heard(note: Path, heard: str | None, transcribed: bool) -> None:
    data = json.loads(note.read_text(encoding="utf-8"))
    data.update({"heard": heard, "transcribed": transcribed})
    note.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
