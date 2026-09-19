"""Context enforcement (PLAN.md §10).

Ollama silently drops the oldest tokens past num_ctx, so the caller gets a
confident answer to half a question. A 400 is the only honest outcome.
"""

from __future__ import annotations

import sys

import pytest

from app import context_guard
from app.context_guard import (
    IMAGE_TOKEN_ESTIMATE,
    count_text_tokens,
    enforce_context,
    estimate_prompt_tokens,
    prewarm_encoder,
    reset_encoder_for_tests,
)
from app.errors import CloudiatorError


@pytest.fixture(autouse=True)
def heuristic_encoder():
    """Pin the character heuristic so counts are deterministic and offline."""
    reset_encoder_for_tests()
    yield
    reset_encoder_for_tests()


def test_within_budget_is_allowed():
    enforce_context(prompt_tokens=100, max_tokens=512, num_ctx=4096)


def test_exactly_at_the_limit_is_allowed():
    enforce_context(prompt_tokens=3584, max_tokens=512, num_ctx=4096)


def test_over_budget_is_rejected_with_both_numbers():
    with pytest.raises(CloudiatorError) as caught:
        enforce_context(prompt_tokens=4000, max_tokens=512, num_ctx=4096)

    error = caught.value
    assert error.status_code == 400
    assert error.code == "context_length_exceeded"
    assert error.param == "messages"
    assert "4000" in error.message
    assert "512" in error.message
    assert "4096" in error.message


def test_rejection_suggests_a_workable_max_tokens():
    with pytest.raises(CloudiatorError) as caught:
        enforce_context(prompt_tokens=4000, max_tokens=512, num_ctx=4096)
    assert "96" in caught.value.message


def test_token_estimate_grows_with_text():
    short = estimate_prompt_tokens([{"role": "user", "content": "hi"}])
    long = estimate_prompt_tokens([{"role": "user", "content": "hi " * 500}])
    assert long > short


def test_estimate_counts_every_message():
    one = estimate_prompt_tokens([{"role": "user", "content": "hello there"}])
    two = estimate_prompt_tokens(
        [
            {"role": "user", "content": "hello there"},
            {"role": "assistant", "content": "hello there"},
        ]
    )
    assert two > one


def test_estimate_charges_for_images():
    text_only = estimate_prompt_tokens(
        [{"role": "user", "content": [{"type": "text", "text": "what is this?"}]}]
    )
    with_image = estimate_prompt_tokens(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                ],
            }
        ]
    )
    assert with_image - text_only == IMAGE_TOKEN_ESTIMATE


def test_estimate_counts_tool_schemas():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "ocr_image",
                "description": "Read text out of an image using Apple Vision",
                "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
            },
        }
    ]
    without = estimate_prompt_tokens([{"role": "user", "content": "read it"}])
    with_tools = estimate_prompt_tokens([{"role": "user", "content": "read it"}], tools)
    assert with_tools > without


def test_estimate_counts_assistant_tool_calls():
    plain = estimate_prompt_tokens([{"role": "assistant", "content": ""}])
    with_calls = estimate_prompt_tokens(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "geocode", "arguments": {"q": "Cairo"}}}
                ],
            }
        ]
    )
    assert with_calls > plain


def test_four_images_overflow_a_4k_context():
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "https://x/a.png"}}] * 4,
        }
    ]
    prompt_tokens = estimate_prompt_tokens(messages)
    with pytest.raises(CloudiatorError):
        enforce_context(prompt_tokens, 512, 4096)


def test_heuristic_is_used_when_the_encoder_is_not_ready():
    assert not context_guard._encoder_ready
    assert count_text_tokens("abcd" * 10) == 10


def test_prewarm_failure_falls_back_to_the_heuristic(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    assert prewarm_encoder() is False
    assert count_text_tokens("hello world") > 0
