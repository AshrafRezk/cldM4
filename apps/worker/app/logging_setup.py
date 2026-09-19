"""Never log Authorization or raw API keys."""

from __future__ import annotations

import logging
import re
from typing import Any

_AUTH_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?\S+")
_KEY_RE = re.compile(r"sk-cld-[A-Za-z0-9_\-]+")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Format first, then redact. Stringifying args in place breaks httpx's
        # 'HTTP Request: ... %d ...' (int 200 -> "200" -> TypeError on %d),
        # which prints "--- Logging error ---" and can abort lifespan warmup.
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = _redact(rendered)
        record.args = ()
        return True


def _redact(text: str) -> str:
    text = _AUTH_RE.sub(r"\1\2[REDACTED]", text)
    text = _KEY_RE.sub("sk-cld-[REDACTED]", text)
    return text


def configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    for handler in logging.root.handlers:
        if not any(isinstance(f, RedactFilter) for f in handler.filters):
            handler.addFilter(RedactFilter())


def headers_for_log(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in dict(headers).items():
        name = str(key)
        if name.lower() == "authorization":
            out[name] = "[REDACTED]"
        else:
            out[name] = _redact(str(value))
    return out
