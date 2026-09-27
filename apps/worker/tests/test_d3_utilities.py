"""Fuzzy match, units, and holidays stay on the library path."""

from __future__ import annotations

from tools.text.handler import run as text_run
from tools.time.handler import run as time_run
from tools.units.handler import run as units_run


async def test_fuzzy_match_ranks_the_supplied_choices():
    result = await text_run({"query": "invoice", "choices": ["weather report", "invoice total"]})
    assert result["matches"][0]["choice"] == "invoice total"


async def test_phone_formats_e164():
    result = await text_run({"action": "phone", "number": "4155552671", "region": "US"})
    assert result["e164"] == "+14155552671"


async def test_kilometers_to_meters():
    result = await units_run({"value": 1, "from": "kilometer", "to": "meter"})
    assert result["value"] == 1000


async def test_new_year_is_a_us_holiday():
    result = await time_run({"country": "US", "date": "2026-01-01"})
    assert result["is_holiday"] is True
    assert result["holiday"]
