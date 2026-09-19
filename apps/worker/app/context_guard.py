"""Pre-flight token estimate. Ollama silently drops oldest tokens on overflow."""

from __future__ import annotations

from typing import Any

import tiktoken

from app.config import Settings
from app.errors import context_length_exceeded
from app.vision import collect_image_urls

_ENCODING = tiktoken.get_encoding("cl100k_base")


def encode_len(text: str) -> int:
    return len(_ENCODING.encode(text, disallowed_special=()))


def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return ""
    if part.get("type") == "text":
        return str(part.get("text") or "")
    return ""


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_part_text(p) for p in content)
    return ""


def estimate_prompt_tokens(messages: list[dict[str, Any]], settings: Settings) -> int:
    total = 0
    for message in messages:
        total += 4  # role framing
        total += encode_len(str(message.get("role") or ""))
        total += encode_len(message_text(message))
        total += settings.vision_tokens_per_image * len(collect_image_urls(message.get("content")))
        if message.get("tool_calls"):
            total += encode_len(str(message.get("tool_calls")))
    return total


def assert_context_fits(
    messages: list[dict[str, Any]],
    max_tokens: int,
    settings: Settings,
    max_context: int | None = None,
) -> int:
    window = max_context if max_context is not None else settings.num_ctx
    window = min(window, settings.max_num_ctx)
    prompt_tokens = estimate_prompt_tokens(messages, settings)
    if prompt_tokens + max_tokens > window:
        raise context_length_exceeded(prompt_tokens, max_tokens, window)
    return prompt_tokens
