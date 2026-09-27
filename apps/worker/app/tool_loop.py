"""FastAPI owns the tool loop. Ollama only proposes calls (PLAN.md §9).

Hard limits: 8 iterations, 75s checked before each iteration, scope re-checked
on every call, and an identical repeated call stops the loop immediately.
On cap, the caller gets a normal completion with finish_reason "stop" — never
a half-serialised tool_calls array.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .auth import KeyRecord, require_capability
from .errors import CloudiatorError
from .maps import MapsClient
from .translation import chat_response_to_openai

log = logging.getLogger("cloudiator.tools")

TOOLS_ROOT = Path(__file__).resolve().parents[1] / "tools"
CHAT_TOOL_ORDER = (
    "ocr_image",
    "geocode",
    "places_nearby",
    "render_chart",
    "stats_describe",
    "sql_on_table",
    "extract_document",
    "image_transform",
    "fuzzy_match",
    "convert_units",
    "render_diagram",
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    capability: str
    timeout_seconds: float
    gpu: bool
    schema: dict[str, Any]
    run: Callable[..., Any]
    rest_path: str


def canonical_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable key order so llama.cpp can reuse the prefix."""
    wrapped = [{"type": "function", "function": schema} for schema in schemas]
    encoded = json.dumps(wrapped, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return json.loads(encoded)


def load_registry() -> dict[str, ToolSpec]:
    registry: dict[str, ToolSpec] = {}
    if not TOOLS_ROOT.is_dir():
        return registry
    for folder in sorted(path for path in TOOLS_ROOT.iterdir() if path.is_dir()):
        schema_path = folder / "schema.json"
        handler_path = folder / "handler.py"
        if not schema_path.is_file() or not handler_path.is_file():
            continue
        schema = json.loads(schema_path.read_text())
        root = str(TOOLS_ROOT.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        module = importlib.import_module(f"tools.{folder.name}.handler")
        name = schema["name"]
        registry[name] = ToolSpec(
            name=name,
            capability=module.CAPABILITY,
            timeout_seconds=float(module.TIMEOUT_SECONDS),
            gpu=bool(module.GPU),
            schema=schema,
            run=module.run,
            rest_path=folder.name,
        )
    return registry


def default_chat_tools(registry: dict[str, ToolSpec], key: KeyRecord) -> list[dict[str, Any]]:
    schemas = [
        registry[name].schema
        for name in CHAT_TOOL_ORDER
        if name in registry and key.has(registry[name].capability)
    ]
    return canonical_tools(schemas)


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _call_signature(calls: list[dict[str, Any]]) -> str:
    normalized = []
    for call in calls:
        function = call.get("function") or {}
        normalized.append(
            {
                "name": function.get("name") or "",
                "arguments": json.dumps(_arguments(function.get("arguments")), sort_keys=True),
            }
        )
    return json.dumps(normalized, sort_keys=True)


class ToolRunner:
    def __init__(
        self,
        settings,
        registry: dict[str, ToolSpec],
        maps: MapsClient,
        artifacts=None,
        scheduler=None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.maps = maps
        self.artifacts = artifacts
        self.scheduler = scheduler

    def _call_kwargs(self, spec: ToolSpec, extra: dict[str, Any]) -> dict[str, Any]:
        params = inspect.signature(spec.run).parameters
        available = {
            "maps": self.maps,
            "settings": self.settings,
            "artifacts": self.artifacts,
            "scheduler": self.scheduler,
            **extra,
        }
        return {name: value for name, value in available.items() if name in params}

    async def execute(self, name: str, arguments: dict[str, Any], key: KeyRecord, **extra: Any) -> dict[str, Any]:
        spec = self.registry.get(name)
        if spec is None or not key.has(spec.capability):
            return {
                "error": "scope_denied",
                "message": f"This key cannot call {name}.",
            }
        if spec.gpu:
            return {
                "error": "not_supported",
                "message": f"{name} takes the Metal slot. POST /v1/jobs and poll the id.",
            }
        try:
            require_capability(key, spec.capability)
            result = await asyncio.wait_for(
                spec.run(arguments, **self._call_kwargs(spec, extra)),
                timeout=spec.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"error": "tool_timeout", "message": f"{name} exceeded {spec.timeout_seconds:.0f}s."}
        except CloudiatorError as exc:
            if exc.code == "scope_denied":
                return {"error": "scope_denied", "message": exc.message}
            return {"error": exc.code, "message": exc.message}
        except Exception as exc:  # noqa: BLE001 - a tool failure stays inside the loop
            log.exception("tool %s failed", name)
            return {"error": "tool_failed", "message": str(exc)}
        return result if isinstance(result, dict) else {"result": result}


async def run_tool_loop(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    options: dict[str, Any],
    response_format: str | None,
    key: KeyRecord,
    prompt_tokens: int,
    ollama,
    scheduler,
    runner: ToolRunner,
    settings,
    started: float,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], int]:
    """Return (OpenAI chat payload, iterations executed)."""
    budget = min(settings.tool_loop_budget_seconds, float(settings.sync_deadline_seconds))
    deadline = started + budget
    iterations = 0
    previous_signature: str | None = None
    conversation = list(messages)
    last_tool_text = ""

    while True:
        if clock() >= deadline:
            break
        if iterations >= settings.max_tool_iterations:
            break
        async with scheduler.chat_slot():
            remaining = deadline - clock()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(
                    ollama.chat(
                        model,
                        conversation,
                        options=options,
                        tools=tools or None,
                        response_format=response_format,
                    ),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                break

        message = raw.get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls:
            payload = chat_response_to_openai(raw, model=model, estimated_prompt_tokens=prompt_tokens)
            return payload, iterations

        signature = _call_signature(calls)
        if signature == previous_signature:
            break
        previous_signature = signature

        conversation.append(message)
        for call in calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            result = await runner.execute(name, _arguments(function.get("arguments")), key)
            last_tool_text = json.dumps(result, ensure_ascii=False)
            conversation.append({"role": "tool", "name": name, "content": last_tool_text})
        iterations += 1

    content = last_tool_text or ""
    payload = chat_response_to_openai(
        {"message": {"role": "assistant", "content": content}, "done_reason": "stop"},
        model=model,
        estimated_prompt_tokens=prompt_tokens,
    )
    payload["choices"][0]["finish_reason"] = "stop"
    payload["choices"][0]["message"].pop("tool_calls", None)
    return payload, iterations
