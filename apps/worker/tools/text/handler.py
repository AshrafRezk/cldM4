"""Fuzzy match, phone numbers, and Salesforce Ids. No model."""

from __future__ import annotations

from typing import Any

from app.errors import CloudiatorError
from tools.salesforce.ids import to_18

NAME = "fuzzy_match"
CAPABILITY = "tools.text"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action") or "fuzzy"
    if action == "fuzzy":
        return _fuzzy(arguments)
    if action == "phone":
        return _phone(arguments)
    if action == "sf_id":
        return _sf_id(arguments)
    raise CloudiatorError(
        400, "invalid_request_error", "action must be fuzzy, phone, or sf_id.", param="action"
    )


def _fuzzy(arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("query")
    choices = arguments.get("choices")
    if not isinstance(query, str) or not query:
        raise CloudiatorError(400, "invalid_request_error", "query is required.", param="query")
    if not isinstance(choices, list) or not choices or not all(isinstance(item, str) for item in choices):
        raise CloudiatorError(400, "invalid_request_error", "choices must be an array of strings.", param="choices")
    if len(choices) > 500:
        raise CloudiatorError(400, "invalid_request_error", "choices is capped at 500.", param="choices")
    from rapidfuzz import fuzz, process

    matches = process.extract(query, choices, scorer=fuzz.WRatio, limit=5)
    return {
        "matches": [{"choice": choice, "score": round(float(score), 2)} for choice, score, _index in matches]
    }


def _phone(arguments: dict[str, Any]) -> dict[str, Any]:
    number = arguments.get("number")
    region = arguments.get("region") or "US"
    if not isinstance(number, str) or not number:
        raise CloudiatorError(400, "invalid_request_error", "number is required.", param="number")
    if not isinstance(region, str) or len(region) != 2:
        raise CloudiatorError(400, "invalid_request_error", "region must be a 2-letter country code.", param="region")
    import phonenumbers

    try:
        parsed = phonenumbers.parse(number, region.upper())
    except phonenumbers.NumberParseException as exc:
        raise CloudiatorError(400, "invalid_request_error", "The phone number could not be parsed.", param="number") from exc
    if not phonenumbers.is_possible_number(parsed):
        raise CloudiatorError(400, "invalid_request_error", "The phone number is not possible.", param="number")
    return {
        "e164": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        "region": region.upper(),
    }


def _sf_id(arguments: dict[str, Any]) -> dict[str, Any]:
    raw = arguments.get("id")
    if not isinstance(raw, str):
        raise CloudiatorError(400, "invalid_request_error", "id is required.", param="id")
    try:
        full = to_18(raw)
    except ValueError as exc:
        raise CloudiatorError(400, "invalid_request_error", str(exc), param="id") from exc
    return {"id15": full[:15], "id18": full}
