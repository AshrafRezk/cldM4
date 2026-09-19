"""OpenAI <-> Ollama translation and the parameter support matrix (PLAN.md §10).

Unsupported parameters are rejected with 400 `not_supported` rather than
ignored. Silently dropping `logit_bias` or `n: 3` produces wrong results the
caller has no way to see.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .errors import CloudiatorError, not_supported

PASSTHROUGH_OPTIONS = {
    "temperature": "temperature",
    "top_p": "top_p",
    "seed": "seed",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
}


def _reject(param: str, reason: str) -> CloudiatorError:
    return not_supported(
        f"{param} is not supported by this appliance: {reason}", param=param
    )


def validate_chat_params(body: dict[str, Any]) -> None:
    if body.get("n") is not None and body["n"] != 1:
        raise _reject("n", "one generation at a time; the Metal slot is single-occupancy")
    if body.get("logprobs"):
        raise _reject("logprobs", "Ollama does not expose per-token logprobs")
    if "top_logprobs" in body and body["top_logprobs"] is not None:
        raise _reject("top_logprobs", "Ollama does not expose per-token logprobs")
    if body.get("best_of") is not None and body["best_of"] != 1:
        raise _reject("best_of", "it multiplies generations on a single Metal slot")
    if body.get("logit_bias"):
        raise _reject("logit_bias", "Ollama does not accept a logit bias map")
    if body.get("stream"):
        raise _reject(
            "stream",
            "streaming arrives with the browser keys in a later phase; Salesforce keys are "
            "non-streaming by design",
        )
    tool_choice = body.get("tool_choice")
    if isinstance(tool_choice, str) and tool_choice not in ("auto", "none"):
        raise _reject("tool_choice", "only 'auto' and 'none' are supported")
    if isinstance(tool_choice, dict):
        raise _reject("tool_choice", "only 'auto' and 'none' are supported")

    response_format = body.get("response_format")
    if response_format is not None:
        if not isinstance(response_format, dict):
            raise _reject("response_format", "expected an object")
        kind = response_format.get("type")
        if kind not in ("text", "json_object"):
            raise _reject(
                "response_format",
                f"{kind!r} is not supported; use 'text' or 'json_object'",
            )


def resolve_max_tokens(body: dict[str, Any], settings) -> int:
    requested = body.get("max_tokens")
    if requested is None:
        requested = body.get("max_completion_tokens")
    if requested is None:
        return settings.max_tokens_default
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        raise not_supported("max_tokens must be a positive integer", param="max_tokens")
    return requested


def resolve_num_ctx(settings) -> int:
    return min(settings.num_ctx, settings.num_ctx_max)


def build_options(body: dict[str, Any], *, num_ctx: int, max_tokens: int) -> dict[str, Any]:
    options: dict[str, Any] = {"num_ctx": num_ctx, "num_predict": max_tokens}
    for openai_name, ollama_name in PASSTHROUGH_OPTIONS.items():
        value = body.get(openai_name)
        if value is not None:
            options[ollama_name] = value
    stop = body.get("stop")
    if stop is not None:
        options["stop"] = [stop] if isinstance(stop, str) else list(stop)
    return options


def _tool_calls_to_openai(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, call in enumerate(raw):
        function = call.get("function", {})
        arguments = function.get("arguments", {})
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, default=str)
        calls.append(
            {
                "id": call.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "index": index,
                "function": {"name": function.get("name", ""), "arguments": arguments},
            }
        )
    return calls


def chat_response_to_openai(
    raw: dict[str, Any],
    *,
    model: str,
    estimated_prompt_tokens: int,
) -> dict[str, Any]:
    message = raw.get("message") or {}
    tool_calls = message.get("tool_calls") or []

    openai_message: dict[str, Any] = {
        "role": message.get("role", "assistant"),
        "content": message.get("content", "") or "",
    }
    if tool_calls:
        openai_message["tool_calls"] = _tool_calls_to_openai(tool_calls)

    if tool_calls:
        finish_reason = "tool_calls"
    elif raw.get("done_reason") == "length":
        finish_reason = "length"
    else:
        finish_reason = "stop"

    prompt_tokens = raw.get("prompt_eval_count") or estimated_prompt_tokens
    completion_tokens = raw.get("eval_count") or 0

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": openai_message,
                "logprobs": None,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def normalize_embeddings_input(value: Any) -> list[str]:
    if value is None:
        raise not_supported("input is required", param="input")
    if isinstance(value, str):
        if not value:
            raise not_supported("input must not be empty", param="input")
        return [value]
    if isinstance(value, list):
        if not value:
            raise not_supported("input must not be empty", param="input")
        if all(isinstance(item, str) for item in value):
            return list(value)
        raise not_supported(
            "pre-tokenised input is not supported; send strings", param="input"
        )
    raise not_supported("input must be a string or a list of strings", param="input")


def embeddings_response_to_openai(
    vectors: list[list[float]], *, model: str, prompt_tokens: int
) -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
        "model": model,
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


def models_response_to_openai(tags: list[dict[str, Any]]) -> dict[str, Any]:
    data = []
    for tag in tags:
        name = tag.get("name") or tag.get("model")
        if not name:
            continue
        data.append(
            {
                "id": name,
                "object": "model",
                "created": 0,
                "owned_by": "cloudiator",
            }
        )
    return {"object": "list", "data": data}
