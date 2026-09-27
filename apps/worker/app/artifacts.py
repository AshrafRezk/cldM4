"""Signed artifact files (PLAN.md §12).

The URL is the capability. A bad or expired signature is 404, never 403, so a
guess does not confirm that an id exists. The resolved path has to stay inside
ARTIFACT_DIR after realpath.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import mimetypes
import time
import uuid
from pathlib import Path

from .errors import CloudiatorError, disk_full
from .system import free_disk_gb

log = logging.getLogger("cloudiator.artifacts")

ID_ALPHABET = set("0123456789abcdef")
JANITOR_SECONDS = 15 * 60
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - bad sig is a 404, not a 500
        raise ValueError("bad signature encoding") from exc


class ArtifactStore:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.root = Path(settings.artifact_dir)

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _secret(self) -> bytes:
        secret = self.settings.artifact_signing_secret
        if not secret or secret.startswith("replace-with"):
            raise CloudiatorError(
                500,
                "internal_error",
                "ARTIFACT_SIGNING_SECRET is not set, so artifact URLs cannot be signed.",
                error_type="server_error",
            )
        return secret.encode("utf-8")

    def assert_disk(self) -> None:
        free = free_disk_gb(str(self.root if self.root.exists() else self.root.parent))
        floor = self.settings.min_free_disk_gb
        if free is not None and free < floor:
            raise disk_full(free, floor)

    def save(self, data: bytes, suffix: str) -> str:
        """Write bytes and return the artifact id. Caller signs it separately."""
        self.assert_disk()
        self.ensure_root()
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        if len(suffix) > 9 or not suffix[1:].isalnum():
            raise CloudiatorError(400, "invalid_request_error", "Unsupported artifact type.")
        artifact_id = uuid.uuid4().hex
        path = (self.root / f"{artifact_id}{suffix.lower()}").resolve()
        if path.parent != self.root.resolve():
            raise CloudiatorError(404, "not_found", "Artifact not found.")
        path.write_bytes(data)
        return artifact_id

    def sign(self, artifact_id: str, *, ttl_seconds: int | None = None) -> str:
        if not self._valid_id(artifact_id) or self._find(artifact_id) is None:
            raise CloudiatorError(404, "not_found", "Artifact not found.")
        ttl = self.settings.artifact_url_ttl_seconds if ttl_seconds is None else ttl_seconds
        exp = int(time.time()) + max(1, ttl)
        sig = _b64(self._mac(artifact_id, exp))
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/artifacts/{artifact_id}?exp={exp}&sig={sig}"

    def verify(self, artifact_id: str, exp: str, sig: str) -> Path:
        """Return the file, or raise 404. Never 403."""
        try:
            expires = int(exp)
        except (TypeError, ValueError):
            raise CloudiatorError(404, "not_found", "Artifact not found.") from None
        if not self._valid_id(artifact_id) or expires < int(time.time()):
            raise CloudiatorError(404, "not_found", "Artifact not found.")
        try:
            presented = _unb64(sig)
            expected = self._mac(artifact_id, expires)
        except (CloudiatorError, ValueError):
            raise CloudiatorError(404, "not_found", "Artifact not found.") from None
        if not hmac.compare_digest(presented, expected):
            raise CloudiatorError(404, "not_found", "Artifact not found.")
        path = self._find(artifact_id)
        if path is None:
            raise CloudiatorError(404, "not_found", "Artifact not found.")
        return path

    def sweep(self, *, now: float | None = None) -> int:
        if not self.root.is_dir():
            return 0
        cutoff = (now if now is not None else time.time()) - self.settings.artifact_ttl_hours * 3600
        removed = 0
        root = self.root.resolve()
        for path in self.root.iterdir():
            try:
                resolved = path.resolve()
                if resolved.parent != root or not resolved.is_file():
                    continue
                if resolved.stat().st_mtime < cutoff:
                    resolved.unlink()
                    removed += 1
            except OSError:
                log.exception("artifact janitor skipped %s", path)
        if removed:
            log.info("artifact janitor removed %s file(s)", removed)
        return removed

    def _mac(self, artifact_id: str, exp: int) -> bytes:
        message = f"{artifact_id}:{exp}".encode("utf-8")
        return hmac.new(self._secret(), message, hashlib.sha256).digest()

    def _find(self, artifact_id: str) -> Path | None:
        if not self._valid_id(artifact_id) or not self.root.is_dir():
            return None
        root = self.root.resolve()
        matches = list(self.root.glob(f"{artifact_id}.*"))
        if len(matches) != 1:
            return None
        resolved = matches[0].resolve()
        if resolved.parent != root or not resolved.is_file():
            return None
        return resolved

    @staticmethod
    def _valid_id(artifact_id: str) -> bool:
        return (
            isinstance(artifact_id, str)
            and len(artifact_id) == 32
            and all(char in ID_ALPHABET for char in artifact_id)
        )


def content_headers(path: Path) -> dict[str, str]:
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"X-Content-Type-Options": "nosniff", "Content-Type": media}
    if media not in _IMAGE_TYPES:
        headers["Content-Disposition"] = "attachment"
    return headers


async def janitor_loop(store: ArtifactStore) -> None:
    while True:
        await asyncio.sleep(JANITOR_SECONDS)
        try:
            await asyncio.to_thread(store.sweep)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("artifact janitor pass failed")
