"""Context enforcement (PLAN.md §10).

Ollama silently drops the oldest tokens when a prompt exceeds `num_ctx`, so the
caller gets a confident answer to half a question. The worker estimates the
prompt first and returns 400 `context_length_exceeded` instead.

tiktoken loads its BPE table from the network on first use. That download must
never happen on a request path, so the encoder is warmed once at startup and
the request path falls back to a character heuristic if it is not ready.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .errors import context_length_exceeded

log = logging.getLogger("cloudiator.context")

ENCODING_NAME = "cl100k_base"
CHARS_PER_TOKEN = 4
PER_MESSAGE_OVERHEAD_TOKENS = 4
# A 1024px-long-edge image is roughly this many tokens on the VLMs in scope.
# Deliberately generous: overestimating rejects a request, underestimating
# lets Ollama truncate it silently.
IMAGE_TOKEN_ESTIMATE = 1024

_encoder: Any | None = None
_encoder_ready = False


def prewarm_encoder() -> bool:
    """Called once at startup. Never called from a request."""
    global _encoder, _encoder_ready
    if _encoder_ready:
        return True
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding(ENCODING_NAME)
        _encoder_ready = True
    except Exception as exc:  # noqa: BLE001 - offline Mini is fine, heuristic takes over
        log.warning("tiktoken unavailable (%s); using the character heuristic", exc)
        _encoder = None
        _encoder_ready = False
    return _encoder_ready


def reset_encoder_for_tests() -> None:
    global _encoder, _encoder_ready
    _encoder = None
    _encoder_ready = False


def count_text_tokens(text: str) -> int:
    if _encoder_ready and _encoder is not None:
        return len(_encoder.encode(text, disallowed_special=()))
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def _content_tokens(content: Any) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return count_text_tokens(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if not isinstance(part, dict):
                total += count_text_tokens(str(part))
                continue
            if part.get("type") == "image_url":
                total += IMAGE_TOKEN_ESTIMATE
            else:
                total += count_text_tokens(str(part.get("text", "")))
        return total
    return count_text_tokens(str(content))


def estimate_prompt_tokens(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> int:
    total = 0
    for message in messages:
        total += PER_MESSAGE_OVERHEAD_TOKENS
        total += count_text_tokens(str(message.get("role", "")))
        total += _content_tokens(message.get("content"))
        if message.get("tool_calls"):
            total += count_text_tokens(json.dumps(message["tool_calls"], default=str))
    if tools:
        total += count_text_tokens(json.dumps(tools, default=str))
    return total


def enforce_context(prompt_tokens: int, max_tokens: int, num_ctx: int) -> None:
    if prompt_tokens + max_tokens <= num_ctx:
        return
    raise context_length_exceeded(
        f"This request needs about {prompt_tokens} prompt tokens plus {max_tokens} completion "
        f"tokens, which exceeds the {num_ctx}-token context for this model. Shorten the prompt "
        f"or lower max_tokens to {max(1, num_ctx - prompt_tokens)}."
    )
