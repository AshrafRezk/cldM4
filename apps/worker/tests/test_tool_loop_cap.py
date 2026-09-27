"""The tool loop stops itself. Ollama never runs the tools."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.auth import KeyRecord
from app.tool_loop import ToolRunner, load_registry, run_tool_loop
from tests.conftest import key_row


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Scheduler:
    @asynccontextmanager
    async def chat_slot(self):
        yield


class Ollama:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, model, messages, *, options, tools=None, response_format=None):
        self.calls += 1
        if not self.replies:
            return {"message": {"role": "assistant", "content": "done"}, "eval_count": 1}
        return self.replies.pop(0)


class Maps:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def geocode_one(self, query: str) -> dict:
        self.queries.append(query)
        return {"lat": 30.0, "lon": 31.0, "display_name": query}


def _tool_reply(name: str, arguments: dict) -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        },
        "prompt_eval_count": 4,
        "eval_count": 2,
    }


def _text_reply(content: str) -> dict:
    return {
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": 4,
        "eval_count": 2,
        "done_reason": "stop",
    }


@pytest.fixture()
def runner(settings):
    maps = Maps()
    built = ToolRunner(settings, load_registry(), maps)
    return built, maps


async def _run(runner, replies, *, clock=None, settings):
    ollama = Ollama(replies)
    payload, iterations = await run_tool_loop(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "geocode"}}],
        model="gemma",
        options={},
        response_format=None,
        key=KeyRecord.from_row(key_row()),
        prompt_tokens=3,
        ollama=ollama,
        scheduler=Scheduler(),
        runner=runner,
        settings=settings,
        started=0.0,
        clock=clock or Clock(),
    )
    return payload, iterations, ollama


async def test_eight_iterations_then_stop_without_tool_calls(settings, runner):
    tool_runner, maps = runner
    replies = [_tool_reply("geocode", {"q": f"place-{index}"}) for index in range(12)]
    payload, iterations, ollama = await _run(tool_runner, replies, settings=settings)

    assert iterations == 8
    assert ollama.calls == 8
    assert len(maps.queries) == 8
    message = payload["choices"][0]["message"]
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert "tool_calls" not in message
    assert "place-7" in message["content"]


async def test_identical_tool_call_breaks_immediately(settings, runner):
    tool_runner, maps = runner
    same = _tool_reply("geocode", {"q": "Cairo"})
    payload, iterations, ollama = await _run(
        tool_runner, [same, same, _text_reply("should not run")], settings=settings
    )

    assert iterations == 1
    assert maps.queries == ["Cairo"]
    assert ollama.calls == 2
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert "tool_calls" not in payload["choices"][0]["message"]


async def test_budget_is_checked_before_the_next_iteration(settings, runner):
    tool_runner, maps = runner
    clock = Clock()

    class Jumping(Ollama):
        async def chat(self, model, messages, *, options, tools=None, response_format=None):
            self.calls += 1
            clock.now = settings.tool_loop_budget_seconds + 1
            return _tool_reply("geocode", {"q": "Cairo"})

    ollama = Jumping([])
    payload, iterations = await run_tool_loop(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gemma",
        options={},
        response_format=None,
        key=KeyRecord.from_row(key_row()),
        prompt_tokens=3,
        ollama=ollama,
        scheduler=Scheduler(),
        runner=tool_runner,
        settings=settings,
        started=0.0,
        clock=clock,
    )

    assert iterations == 1
    assert ollama.calls == 1
    assert maps.queries == ["Cairo"]
    assert "tool_calls" not in payload["choices"][0]["message"]


async def test_invented_tool_is_scope_denied_and_the_loop_continues(settings, runner):
    tool_runner, maps = runner
    payload, iterations, _ollama = await _run(
        tool_runner,
        [
            _tool_reply("flux_generate", {"prompt": "a bicycle"}),
            _text_reply("I cannot generate that image."),
        ],
        settings=settings,
    )

    assert iterations == 1
    assert maps.queries == []
    assert payload["choices"][0]["message"]["content"] == "I cannot generate that image."


def test_sync_chat_tools_are_cpu_only():
    """FLUX is registered for the job queue. The sync chat loop must not run it."""
    from app.tool_loop import CHAT_TOOL_ORDER

    registry = load_registry()
    for name in CHAT_TOOL_ORDER:
        spec = registry.get(name)
        if spec is not None:
            assert spec.gpu is False
    flux = registry["flux_generate"]
    assert flux.gpu is True
    assert flux.name not in CHAT_TOOL_ORDER
