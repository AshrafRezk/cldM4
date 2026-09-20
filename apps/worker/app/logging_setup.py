"""Logging with credentials scrubbed.

PLAN.md §12: strip `Authorization` from every log path, including exception
handlers and request dumps. A filter on the root logger is the only place that
holds for code nobody has written yet.
"""

from __future__ import annotations

import logging
import re

REDACTED = "[redacted]"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

PATTERNS = (
    (re.compile(r"(?i)\b(authorization|proxy-authorization)\b\s*[:=]\s*\S+"), REDACTED),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]+=*"), REDACTED),
    (re.compile(r"sk-cld-[A-Za-z0-9_\-]+"), REDACTED),
    (re.compile(r"(?i)\bcf-access-jwt-assertion\b\s*[:=]\s*\S+"), REDACTED),
    (re.compile(r"(?i)\bx-admin-token\b\s*[:=]\s*\S+"), REDACTED),
    # A Neon connection error carries the whole DSN. Keep the host, which is what
    # makes the error readable, and drop the credentials.
    (re.compile(r"(?i)\b(postgres(?:ql)?://)[^@/\s'\"]+@"), r"\1" + REDACTED + "@"),
)


def scrub(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    """Scrubs the formatted record, tracebacks included.

    The filter below cannot see a traceback: `logging` renders `exc_info` after
    filters run. An exception handler that dumps a request is exactly the log
    path PLAN.md §12 is worried about.
    """

    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


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
            format=LOG_FORMAT,
        )
    redactor = RedactingFilter()
    root.setLevel(level)
    for handler in root.handlers:
        if not any(isinstance(existing, RedactingFilter) for existing in handler.filters):
            handler.addFilter(redactor)
        if not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactingFilter) for existing in logger.filters):
            logger.addFilter(redactor)
