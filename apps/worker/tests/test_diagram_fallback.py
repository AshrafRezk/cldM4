"""Mermaid stays off. Graphviz renders, and a timed-out child process group dies."""

from __future__ import annotations

import pytest

from app import main
from app.procgroup import run_group
from tools.diagram.handler import run as diagram_run


async def test_mermaid_disabled_renders_with_graphviz(make_client, install_key):
    assert main.settings.enable_mermaid is False
    _record, headers = install_key(capabilities=["tools.diagrams"])
    source = "digraph { apples -> pears }"
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/tools/diagram",
            json={"source": source, "engine": "mermaid"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["engine"] == "graphviz"
        path = body["url"].removeprefix(main.settings.public_base_url)
        png = await client.get(path)
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")


async def test_a_direct_graphviz_render_does_not_call_mmdc(monkeypatch):
    called = []

    async def forbid(*args, **kwargs):
        called.append(args)
        raise AssertionError("mmdc must not run while ENABLE_MERMAID is false")

    monkeypatch.setattr("tools.diagram.handler._mermaid", forbid)
    result = await diagram_run(
        {"source": "digraph { a -> b }"},
        settings=main.settings,
        artifacts=main.artifacts,
        scheduler=main.scheduler,
    )
    assert result["engine"] == "graphviz"
    assert called == []


async def test_timeout_kills_the_process_group():
    with pytest.raises(TimeoutError):
        await run_group(["sleep", "30"], timeout=0.2)
