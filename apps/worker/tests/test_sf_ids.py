"""15-character Salesforce Ids gain the case-safe suffix and round-trip."""

from __future__ import annotations

import pytest

from tools.salesforce.ids import to_18
from tools.text.handler import run as text_run


def test_15_converts_to_18_and_round_trips():
    id15 = "001D000000IRt53"
    id18 = to_18(id15)
    assert id18 == "001D000000IRt53IAD"
    assert len(id18) == 18
    assert id18[:15] == id15
    assert to_18(id18) == id18


def test_a_bad_length_is_rejected():
    with pytest.raises(ValueError):
        to_18("001")


async def test_the_text_route_returns_both_forms():
    result = await text_run({"action": "sf_id", "id": "001D000000IRt53"})
    assert result == {"id15": "001D000000IRt53", "id18": "001D000000IRt53IAD"}
