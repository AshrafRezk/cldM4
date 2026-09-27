"""Unit conversion with pint. Rates and factors are computed, never guessed."""

from __future__ import annotations

from typing import Any

from app.errors import CloudiatorError

NAME = "convert_units"
CAPABILITY = "tools.units"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    value = arguments.get("value")
    src = arguments.get("from") or arguments.get("from_unit")
    dst = arguments.get("to") or arguments.get("to_unit")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CloudiatorError(400, "invalid_request_error", "value must be a number.", param="value")
    if not isinstance(src, str) or not src or not isinstance(dst, str) or not dst:
        raise CloudiatorError(400, "invalid_request_error", "from and to units are required.", param="from")
    if len(src) > 40 or len(dst) > 40:
        raise CloudiatorError(400, "invalid_request_error", "unit names are capped at 40 characters.", param="from")
    from pint import UnitRegistry
    from pint.errors import DimensionalityError, UndefinedUnitError

    registry = _registry()
    try:
        quantity = registry.Quantity(float(value), src).to(dst)
    except UndefinedUnitError as exc:
        raise CloudiatorError(400, "invalid_request_error", "Unknown unit.", param="from") from exc
    except DimensionalityError as exc:
        raise CloudiatorError(400, "invalid_request_error", "Those units do not convert.", param="to") from exc
    return {"value": float(quantity.magnitude), "unit": f"{quantity.units}", "from": src, "to": dst}


def _registry():
    global _UREG
    if _UREG is None:
        from pint import UnitRegistry

        _UREG = UnitRegistry()
    return _UREG


_UREG = None
