"""A missing kaleido must not fail the chart request or the worker import."""

from __future__ import annotations

import sys

from app import main


def test_kaleido_is_not_imported_with_the_worker():
    assert "kaleido" not in sys.modules
    import tools.chart.handler  # noqa: F401

    assert "kaleido" not in sys.modules


async def test_plotly_without_kaleido_falls_back_to_matplotlib(make_client, install_key):
    assert "kaleido" not in sys.modules
    _record, headers = install_key(capabilities=["tools.charts"])
    body = {
        "kind": "bar",
        "title": "Fruit",
        "engine": "plotly",
        "x": ["apples", "pears"],
        "series": [{"name": "n", "values": [5, 4]}],
    }
    async with make_client(headers) as client:
        response = await client.post("/v1/tools/chart", json=body)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["engine"] == "matplotlib"
        path = payload["url"].removeprefix(main.settings.public_base_url)
        png = await client.get(path)
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")
    assert png.headers["content-type"].startswith("image/png")
    assert png.headers["x-content-type-options"] == "nosniff"
    assert "kaleido" not in sys.modules


async def test_matplotlib_chart_does_not_take_the_cpu_heavy_slot(make_client, install_key, monkeypatch):
    entered = {"count": 0}
    real = main.scheduler.cpu_heavy_slot

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def counting():
        entered["count"] += 1
        async with real():
            yield

    monkeypatch.setattr(main.scheduler, "cpu_heavy_slot", counting)
    _record, headers = install_key(capabilities=["tools.charts"])
    body = {"x": ["a"], "series": [{"name": "n", "values": [1]}]}
    async with make_client(headers) as client:
        response = await client.post("/v1/tools/chart", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["engine"] == "matplotlib"
    assert entered["count"] == 0
