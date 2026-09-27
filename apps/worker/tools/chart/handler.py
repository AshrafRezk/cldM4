"""Chart PNG. Matplotlib is the default. Plotly is optional and never required to import."""

from __future__ import annotations

import asyncio
import io
import os
from typing import Any

from app.errors import CloudiatorError

os.environ.setdefault("MPLBACKEND", "Agg")

NAME = "render_chart"
CAPABILITY = "tools.charts"
TIMEOUT_SECONDS = 30
GPU = False

_KINDS = {"bar", "line", "scatter"}
_MAX_POINTS = 10_000


async def run(arguments: dict[str, Any], *, artifacts, scheduler=None) -> dict[str, Any]:
    spec = _spec(arguments)
    engine = spec["engine"]
    if engine == "plotly":
        if scheduler is None:
            png = await asyncio.to_thread(_matplotlib_png, spec)
            used = "matplotlib"
        else:
            async with scheduler.cpu_heavy_slot():
                png, used = await asyncio.to_thread(_plotly_or_matplotlib, spec)
    else:
        png = await asyncio.to_thread(_matplotlib_png, spec)
        used = "matplotlib"
    artifact_id = artifacts.save(png, ".png")
    return {"id": artifact_id, "url": artifacts.sign(artifact_id), "engine": used}


def _spec(arguments: dict[str, Any]) -> dict[str, Any]:
    kind = arguments.get("kind") or "bar"
    if kind not in _KINDS:
        raise CloudiatorError(400, "invalid_request_error", "kind must be bar, line, or scatter.", param="kind")
    engine = arguments.get("engine") or "matplotlib"
    if engine not in {"matplotlib", "plotly"}:
        raise CloudiatorError(
            400, "invalid_request_error", "engine must be matplotlib or plotly.", param="engine"
        )
    labels = arguments.get("x")
    series = arguments.get("series")
    if not isinstance(labels, list) or not labels:
        raise CloudiatorError(400, "invalid_request_error", "x is required.", param="x")
    if len(labels) > _MAX_POINTS:
        raise CloudiatorError(400, "invalid_request_error", f"x is capped at {_MAX_POINTS} points.", param="x")
    if not isinstance(series, list) or not series:
        raise CloudiatorError(400, "invalid_request_error", "series is required.", param="series")
    parsed = []
    for item in series:
        if not isinstance(item, dict):
            raise CloudiatorError(400, "invalid_request_error", "each series entry must be an object.", param="series")
        name = item.get("name") or "series"
        if not isinstance(name, str):
            raise CloudiatorError(400, "invalid_request_error", "series name must be a string.", param="series")
        values = _numbers(item.get("values"), len(labels))
        parsed.append({"name": name[:80], "values": values})
    title = arguments.get("title") or ""
    if not isinstance(title, str):
        raise CloudiatorError(400, "invalid_request_error", "title must be a string.", param="title")
    return {
        "kind": kind,
        "engine": engine,
        "title": title[:200],
        "x": [str(label) for label in labels],
        "series": parsed,
    }


def _numbers(values: Any, width: int) -> list[float]:
    if not isinstance(values, list) or len(values) != width:
        raise CloudiatorError(
            400, "invalid_request_error", "each series values array must match x.", param="series"
        )
    numbers = []
    for value in values:
        if isinstance(value, bool) or value is None:
            raise CloudiatorError(400, "invalid_request_error", "series values must be numbers.", param="series")
        if isinstance(value, (int, float)):
            numbers.append(float(value))
            continue
        if isinstance(value, str):
            try:
                numbers.append(float(value))
            except ValueError as exc:
                raise CloudiatorError(
                    400, "invalid_request_error", "series values must be numbers.", param="series"
                ) from exc
            continue
        raise CloudiatorError(400, "invalid_request_error", "series values must be numbers.", param="series")
    return numbers


def _matplotlib_png(spec: dict[str, Any]) -> bytes:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=100)
    try:
        labels = spec["x"]
        positions = list(range(len(labels)))
        kind = spec["kind"]
        for item in spec["series"]:
            values = item["values"]
            if kind == "bar":
                ax.bar(positions, values, label=item["name"])
            elif kind == "line":
                ax.plot(positions, values, label=item["name"])
            else:
                ax.scatter(positions, values, label=item["name"])
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=30 if len(labels) > 6 else 0, ha="right")
        if spec["title"]:
            ax.set_title(spec["title"])
        if len(spec["series"]) > 1:
            ax.legend()
        fig.tight_layout()
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        return buffer.getvalue()
    finally:
        plt.close(fig)


def _plotly_or_matplotlib(spec: dict[str, Any]) -> tuple[bytes, str]:
    """Kaleido is optional. A missing or crashed renderer falls back to matplotlib."""
    try:
        import plotly.graph_objects as go
        import plotly.io as pio
    except ImportError:
        return _matplotlib_png(spec), "matplotlib"
    fig = go.Figure()
    for item in spec["series"]:
        trace = {"bar": go.Bar, "line": go.Scatter, "scatter": go.Scatter}[spec["kind"]]
        mode = "lines" if spec["kind"] == "line" else "markers" if spec["kind"] == "scatter" else None
        kwargs = {"x": spec["x"], "y": item["values"], "name": item["name"]}
        if mode:
            kwargs["mode"] = mode
        fig.add_trace(trace(**kwargs))
    if spec["title"]:
        fig.update_layout(title=spec["title"])
    try:
        png = pio.to_image(fig, format="png")
    except Exception:  # noqa: BLE001 - kaleido missing or Chromium crashed
        return _matplotlib_png(spec), "matplotlib"
    if not png:
        return _matplotlib_png(spec), "matplotlib"
    return png, "plotly"
