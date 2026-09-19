"""OpenAI request/response translation and the unsupported-parameter matrix."""

from __future__ import annotations

import time
import uuid
from typing import Any

from app.config import Settings
from app.errors import not_supported
from app.vision import collect_image_urls, prepare_images

REJECT_IF_PRESENT = ("logprobs", "top_logprobs", "best_of", "logit_bias")


def reject_unsupported(body: dict[str, Any]) -> None:
    n = body.get("n")
    if n is not None and n != 1:
        raise not_supported("Only n=1 is supported on this appliance", param="n")
    for key in REJECT_IF_PRESENT:
        if key in body and body[key] not in (None, False, 0, {}, []):
            raise not_supported(f"Parameter `{key}` is not supported", param=key)
        if key in body and body[key] is True:
            raise not_supported(f"Parameter `{key}` is not supported", param=key)
    # logprobs: false is ok; logprobs: true is not. Presence of logit_bias {} is still a client using it.
    if body.get("logprobs") is True:
        raise not_supported("Parameter `logprobs` is not supported", param="logprobs")
    if "logit_bias" in body and body["logit_bias"] is not None:
        raise not_supported("Parameter `logit_bias` is not supported", param="logit_bias")
    if body.get("top_logprobs"):
        raise not_supported("Parameter `top_logprobs` is not supported", param="top_logprobs")
    if body.get("best_of") not in (None, 1):
        raise not_supported("Parameter `best_of` is not supported", param="best_of")
    tool_choice = body.get("tool_choice")
    if tool_choice == "required":
        raise not_supported(
            'tool_choice="required" is not supported in Phase A',
            param="tool_choice",
        )


def openai_chat_response(
    ollama_body: dict[str, Any],
    *,
    model: str,
    prompt_tokens: int | None = None,
) -> dict[str, Any]:
    message = ollama_body.get("message") or {}
    finish = "stop"
    if ollama_body.get("done_reason") == "length":
        finish = "length"
    tool_calls = message.get("tool_calls")
    openai_message: dict[str, Any] = {
        "role": message.get("role") or "assistant",
        "content": message.get("content") if not tool_calls else message.get("content") or None,
    }
    if tool_calls:
        openai_message["tool_calls"] = _translate_tool_calls(tool_calls)
        finish = "tool_calls"
    prompt = ollama_body.get("prompt_eval_count")
    completion = ollama_body.get("eval_count") or 0
    if prompt is None:
        prompt = prompt_tokens or 0
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": openai_message,
                "finish_reason": finish,
            }
        ],
        "usage": {
            "prompt_tokens": int(prompt),
            "completion_tokens": int(completion),
            "total_tokens": int(prompt) + int(completion),
        },
    }


def openai_stream_chunk(
    ollama_body: dict[str, Any],
    *,
    model: str,
    chunk_id: str,
) -> dict[str, Any]:
    message = ollama_body.get("message") or {}
    delta: dict[str, Any] = {}
    content = message.get("content")
    if content:
        delta["content"] = content
    finish = None
    if ollama_body.get("done"):
        finish = "stop"
        if ollama_body.get("done_reason") == "length":
            finish = "length"
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def openai_embeddings_response(
    ollama_body: dict[str, Any],
    *,
    model: str,
    prompt_tokens: int,
) -> dict[str, Any]:
    vectors: list[list[float]] = []
    if "embeddings" in ollama_body:
        raw = ollama_body["embeddings"]
        if raw and isinstance(raw[0], list):
            vectors = raw
        elif raw:
            vectors = [raw]
    elif "embedding" in ollama_body:
        vectors = [list(ollama_body["embedding"])]
    data = [
        {"object": "embedding", "embedding": vector, "index": i}
        for i, vector in enumerate(vectors)
    ]
    return {
        "object": "list",
        "data": data,
        "model": model,
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


def openai_models_list(tags: list[dict[str, Any]]) -> dict[str, Any]:
    data = []
    for tag in tags:
        name = tag.get("name") or tag.get("model")
        if not name:
            continue
        created = 0
        data.append(
            {
                "id": name,
                "object": "model",
                "created": created,
                "owned_by": "cloudiator",
            }
        )
    return {"object": "list", "data": data}


def build_ollama_chat_payload(
    body: dict[str, Any],
    settings: Settings,
    ollama_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    model = body.get("model") or settings.default_model
    max_tokens = int(body.get("max_tokens") or settings.max_tokens_default)
    num_ctx = min(int(body.get("num_ctx") or settings.num_ctx), settings.max_num_ctx)
    options: dict[str, Any] = {
        "num_ctx": num_ctx,
        "num_predict": max_tokens,
    }
    for src, dest in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("seed", "seed"),
        ("stop", "stop"),
        ("presence_penalty", "presence_penalty"),
        ("frequency_penalty", "frequency_penalty"),
    ):
        if body.get(src) is not None:
            options[dest] = body[src]
    payload: dict[str, Any] = {
        "model": model,
        "messages": ollama_messages,
        "options": options,
    }
    if body.get("tools"):
        payload["tools"] = body["tools"]
    if body.get("tool_choice") in {"auto", "none"}:
        payload["tool_choice"] = body["tool_choice"]
    fmt = body.get("response_format")
    if isinstance(fmt, dict) and fmt.get("type") == "json_object":
        payload["format"] = "json"
    return payload


async def openai_messages_to_ollama(
    messages: list[dict[str, Any]],
    settings: Settings,
    *,
    vision_supported: bool,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        images = await prepare_images(content, settings, vision_supported=vision_supported)
        text = _content_to_text(content)
        out: dict[str, Any] = {
            "role": message.get("role") or "user",
            "content": text,
        }
        if images:
            # Ollama wants raw base64 strings without the data: prefix.
            import base64

            out["images"] = [base64.b64encode(img).decode("ascii") for img in images]
        if message.get("tool_calls"):
            out["tool_calls"] = message["tool_calls"]
        if message.get("name"):
            out["name"] = message["name"]
        converted.append(out)
    return converted


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
        return "\n".join(p for p in parts if p)
    return str(content)


def _translate_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, call in enumerate(tool_calls):
        fn = call.get("function") or call
        name = fn.get("name")
        arguments = fn.get("arguments")
        if isinstance(arguments, dict):
            import json

            arguments = json.dumps(arguments)
        out.append(
            {
                "id": call.get("id") or f"call_{i}",
                "type": "function",
                "function": {"name": name, "arguments": arguments or "{}"},
            }
        )
    return out


def count_images(messages: list[dict[str, Any]]) -> int:
    return sum(len(collect_image_urls(m.get("content"))) for m in messages)
