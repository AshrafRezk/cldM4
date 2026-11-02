"""TwiML builders. Every string from a script or a caller is XML-escaped here."""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def _attrs(**values: object) -> str:
    parts = []
    for name, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f" {name}={quoteattr(str(value))}")
    return "".join(parts)


def say(text: str, *, voice: str | None = None, language: str | None = None) -> str:
    return f"<Say{_attrs(voice=voice, language=language)}>{escape(text)}</Say>"


def gather(
    inner: str,
    *,
    action: str,
    language: str | None,
    timeout: int,
    speech_timeout: str,
) -> str:
    # actionOnEmptyResult: silence still posts to `action`, so the engine owns
    # retries instead of Twilio falling through to the next verb.
    attrs = _attrs(
        input="speech",
        action=action,
        method="POST",
        language=language,
        timeout=timeout,
        speechTimeout=speech_timeout,
        actionOnEmptyResult=True,
    )
    return f"<Gather{attrs}>{inner}</Gather>"


def hangup() -> str:
    return "<Hangup/>"


def response(*verbs: str) -> str:
    return f"{XML_HEADER}<Response>{''.join(verbs)}</Response>"
