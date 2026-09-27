"""Numeric summaries. The model may describe the result. It does not recompute it."""

from __future__ import annotations

from typing import Any

from app.errors import CloudiatorError

NAME = "stats_describe"
CAPABILITY = "tools.stats"
TIMEOUT_SECONDS = 30
GPU = False

_ACTIONS = {"describe", "ttest", "ols", "monte_carlo", "npv"}
_MAX_N = 100_000


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action") or "describe"
    if action == "ttest_ind":
        action = "ttest"
    if action not in _ACTIONS:
        raise CloudiatorError(
            400,
            "invalid_request_error",
            "action must be describe, ttest, ols, monte_carlo, or npv.",
            param="action",
        )
    if action == "describe":
        return {"action": action, **_describe(_numbers(arguments.get("values"), "values"))}
    if action == "ttest":
        return {"action": action, **_ttest(_numbers(arguments.get("a"), "a"), _numbers(arguments.get("b"), "b"))}
    if action == "ols":
        return {"action": action, **_ols(_numbers(arguments.get("y"), "y"), arguments.get("x"))}
    if action == "monte_carlo":
        return {"action": action, **_monte_carlo(arguments)}
    return {"action": action, **_npv(arguments)}


def _numbers(values: Any, param: str) -> list[float]:
    if not isinstance(values, list) or not values:
        raise CloudiatorError(400, "invalid_request_error", f"{param} must be a non-empty array of numbers.", param=param)
    if len(values) > _MAX_N:
        raise CloudiatorError(400, "invalid_request_error", f"{param} is capped at {_MAX_N} values.", param=param)
    numbers = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CloudiatorError(400, "invalid_request_error", f"{param} must be numbers.", param=param)
        numbers.append(float(value))
    return numbers


def _describe(values: list[float]) -> dict[str, Any]:
    import numpy as np

    array = np.asarray(values, dtype=float)
    percentiles = np.percentile(array, [25, 50, 75])
    summary = {
        "count": int(array.size),
        "mean": float(array.mean()),
        "min": float(array.min()),
        "p25": float(percentiles[0]),
        "p50": float(percentiles[1]),
        "p75": float(percentiles[2]),
        "max": float(array.max()),
    }
    if array.size >= 2:
        summary["std"] = float(array.std(ddof=1))
    return summary


def _ttest(left: list[float], right: list[float]) -> dict[str, Any]:
    if len(left) < 2 or len(right) < 2:
        raise CloudiatorError(400, "invalid_request_error", "ttest needs at least two values on each side.")
    from scipy import stats

    result = stats.ttest_ind(left, right, equal_var=False)
    return {
        "statistic": float(result.statistic),
        "pvalue": float(result.pvalue),
        "a_mean": float(sum(left) / len(left)),
        "b_mean": float(sum(right) / len(right)),
    }


def _ols(y: list[float], x: Any) -> dict[str, Any]:
    import numpy as np
    from scipy import stats

    if not isinstance(x, list) or not x:
        raise CloudiatorError(400, "invalid_request_error", "x is required.", param="x")
    if x and isinstance(x[0], list):
        predictors = [ _numbers(row, "x") for row in x ]
        if any(len(row) != len(y) for row in predictors):
            raise CloudiatorError(400, "invalid_request_error", "each x row must match y.", param="x")
        design_x = np.asarray(predictors, dtype=float).T
    else:
        design_x = np.asarray(_numbers(x, "x"), dtype=float).reshape(-1, 1)
        if design_x.shape[0] != len(y):
            raise CloudiatorError(400, "invalid_request_error", "x must match y.", param="x")
    y_arr = np.asarray(y, dtype=float)
    design = np.column_stack([np.ones(len(y_arr)), design_x])
    coef, _, _, _ = np.linalg.lstsq(design, y_arr, rcond=None)
    fitted = design @ coef
    resid = y_arr - fitted
    n, k = design.shape
    sse = float(np.sum(resid**2))
    sst = float(np.sum((y_arr - y_arr.mean()) ** 2))
    rsquared = 1.0 if sst == 0 else 1.0 - sse / sst
    dof = n - k
    pvalues: list[float | None]
    if dof > 0:
        sigma2 = sse / dof
        xtx_inv = np.linalg.pinv(design.T @ design)
        se = np.sqrt(np.maximum(np.diag(xtx_inv) * sigma2, 0))
        with np.errstate(divide="ignore", invalid="ignore"):
            tstats = np.divide(coef, se, out=np.zeros_like(coef), where=se > 0)
        pvalues = [float(value) for value in 2 * stats.t.sf(np.abs(tstats), dof)]
    else:
        pvalues = [None] * k
    return {
        "coefficients": [float(value) for value in coef],
        "pvalues": pvalues,
        "rsquared": float(rsquared),
        "n": int(n),
    }


def _monte_carlo(arguments: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    n = arguments.get("n") or 1000
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= _MAX_N:
        raise CloudiatorError(400, "invalid_request_error", f"n must be an integer from 1 to {_MAX_N}.", param="n")
    mean = arguments.get("mean", 0)
    std = arguments.get("std", 1)
    if isinstance(mean, bool) or not isinstance(mean, (int, float)):
        raise CloudiatorError(400, "invalid_request_error", "mean must be a number.", param="mean")
    if isinstance(std, bool) or not isinstance(std, (int, float)) or float(std) < 0:
        raise CloudiatorError(400, "invalid_request_error", "std must be a non-negative number.", param="std")
    seed = arguments.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise CloudiatorError(400, "invalid_request_error", "seed must be an integer.", param="seed")
    draws = np.random.default_rng(seed).normal(float(mean), float(std), size=n)
    percentiles = np.percentile(draws, [5, 50, 95])
    return {
        "n": n,
        "mean": float(draws.mean()),
        "std": float(draws.std(ddof=1)) if n > 1 else 0.0,
        "p05": float(percentiles[0]),
        "p50": float(percentiles[1]),
        "p95": float(percentiles[2]),
    }


def _npv(arguments: dict[str, Any]) -> dict[str, Any]:
    rate = arguments.get("rate")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or float(rate) <= -1:
        raise CloudiatorError(400, "invalid_request_error", "rate must be a number greater than -1.", param="rate")
    cashflows = _numbers(arguments.get("cashflows"), "cashflows")
    discount = float(rate)
    value = sum(cash / (1 + discount) ** period for period, cash in enumerate(cashflows))
    return {"npv": value, "rate": discount, "periods": len(cashflows)}
