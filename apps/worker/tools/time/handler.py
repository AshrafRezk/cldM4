"""Public holidays for a country and date. The calendar comes from the holidays library."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.errors import CloudiatorError

NAME = "holiday_on"
CAPABILITY = "tools.time"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    country = arguments.get("country")
    raw_date = arguments.get("date")
    if not isinstance(country, str) or len(country) != 2:
        raise CloudiatorError(400, "invalid_request_error", "country must be a 2-letter code.", param="country")
    if not isinstance(raw_date, str):
        raise CloudiatorError(400, "invalid_request_error", "date must be YYYY-MM-DD.", param="date")
    try:
        day = dt.date.fromisoformat(raw_date)
    except ValueError as exc:
        raise CloudiatorError(400, "invalid_request_error", "date must be YYYY-MM-DD.", param="date") from exc
    import holidays

    try:
        calendar = holidays.country_holidays(country.upper(), years=day.year)
    except NotImplementedError as exc:
        raise CloudiatorError(400, "invalid_request_error", "Unsupported country.", param="country") from exc
    name = calendar.get(day)
    return {
        "country": country.upper(),
        "date": raw_date,
        "holiday": name or "",
        "is_holiday": name is not None,
    }
