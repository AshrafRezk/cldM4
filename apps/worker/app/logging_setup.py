"""Never log Authorization or raw API keys."""

from __future__ import annotations

import logging
import re
from typing import Any

_AUTH_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?\S+")
_KEY_RE = re.compile(r"sk-cld-[A-Za-z0-9_\-]+")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact(str(v)) for k, v in record.args.items()}
            else:
                record.args = tuple(_redact(str(a)) for a in record.args)
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
    filt = RedactFilter()
    for handler in logging.root.handlers:
        handler.addFilter(filt)


def headers_for_log(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in dict(headers).items():
        name = str(key)
        if name.lower() == "authorization":
            out[name] = "[REDACTED]"
        else:
            out[name] = _redact(str(value))
    return out
