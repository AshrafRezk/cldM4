"""Logging with credentials scrubbed.

PLAN.md §12: strip `Authorization` from every log path, including exception
handlers and request dumps. A filter on the root logger is the only place that
holds for code nobody has written yet.
"""

from __future__ import annotations

import logging
import re

REDACTED = "[redacted]"

PATTERNS = (
    re.compile(r"(?i)\b(authorization|proxy-authorization)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]+=*"),
    re.compile(r"sk-cld-[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)\bcf-access-jwt-assertion\b\s*[:=]\s*\S+"),
)


def scrub(text: str) -> str:
    for pattern in PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: _scrub_value(value) for key, value in record.args.items()}
            else:
                record.args = tuple(_scrub_value(value) for value in record.args)
        return True


def _scrub_value(value: object) -> object:
    return scrub(value) if isinstance(value, str) else value


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    redactor = RedactingFilter()
    root.setLevel(level)
    for handler in root.handlers:
        if not any(isinstance(existing, RedactingFilter) for existing in handler.filters):
            handler.addFilter(redactor)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactingFilter) for existing in logger.filters):
            logger.addFilter(redactor)
