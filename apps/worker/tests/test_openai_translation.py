"""OpenAI <-> Ollama translation and the parameter matrix (PLAN.md §10).

Unsupported parameters must fail loudly. A silently ignored `n: 3` or
`logit_bias` gives the caller a wrong answer they cannot detect.
"""

from __future__ import annotations

import json

import pytest

from app.errors import CloudiatorError
from app.ollama import OllamaClient, normalize_tag
from app.translation import (
    build_options,
    chat_response_to_openai,
    embeddings_response_to_openai,
    models_response_to_openai,
    normalize_embeddings_input,
    resolve_max_tokens,
    resolve_num_ctx,
    validate_chat_params,
)

BASE = {"model": "qwen3.5:9b", "messages": [{"role": "user", "content": "hi"}]}


@pytest.mark.parametrize(
    "overrides,param",
    [
        ({"n": 2}, "n"),
        ({"logprobs": True}, "logprobs"),
        ({"top_logprobs": 3}, "top_logprobs"),
        ({"best_of": 4}, "best_of"),
        ({"logit_bias": {"50256": -100}}, "logit_bias"),
        ({"stream": True}, "stream"),
        ({"tool_choice": "required"}, "tool_choice"),
        ({"tool_choice": {"type": "function", "function": {"name": "x"}}}, "tool_choice"),
        ({"response_format": {"type": "json_schema"}}, "response_format"),
    ],
)
def test_unsupported_parameters_are_rejected(overrides, param):
    with pytest.raises(CloudiatorError) as caught:
        validate_chat_params({**BASE, **overrides})

    error = caught.value
    assert error.status_code == 400
    assert error.code == "not_supported"
    assert error.param == param


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"n": 1},
        {"best_of": 1},
        {"logprobs": False},
        {"stream": False},
        {"temperature": 0.2, "top_p": 0.9, "seed": 7},
        {"stop": ["\n\n"], "presence_penalty": 0.1, "frequency_penalty": 0.1},
        {"tool_choice": "auto"},
        {"tool_choice": "none"},
        {"response_format": {"type": "json_object"}},
        {"response_format": {"type": "text"}},
    ],
)
def test_supported_parameters_are_accepted(overrides):
    validate_chat_params({**BASE, **overrides})


def test_error_body_is_openai_shaped():
    with pytest.raises(CloudiatorError) as caught:
        validate_chat_params({**BASE, "n": 5})

    body = caught.value.body()
    assert set(body["error"]) == {"message", "type", "param", "code"}
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "not_supported"


def test_max_tokens_defaults_to_the_salesforce_budget(settings):
    assert resolve_max_tokens({}, settings) == 512


def test_max_completion_tokens_is_honoured(settings):
    assert resolve_max_tokens({"max_completion_tokens": 64}, settings) == 64


def test_max_tokens_wins_over_max_completion_tokens(settings):
    assert resolve_max_tokens({"max_tokens": 16, "max_completion_tokens": 64}, settings) == 16


@pytest.mark.parametrize("value", [0, -1, "16", 1.5, True])
def test_bad_max_tokens_is_rejected(settings, value):
    with pytest.raises(CloudiatorError):
        resolve_max_tokens({"max_tokens": value}, settings)


def test_num_ctx_is_clamped_to_the_documented_ceiling(settings):
    assert resolve_num_ctx(settings) == 4096


def test_options_carry_the_context_and_completion_caps():
    options = build_options(BASE, num_ctx=4096, max_tokens=512)
    assert options["num_ctx"] == 4096
    assert options["num_predict"] == 512


def test_options_pass_through_sampling_parameters():
    options = build_options(
        {**BASE, "temperature": 0.2, "top_p": 0.8, "seed": 11, "presence_penalty": 0.5},
        num_ctx=4096,
        max_tokens=128,
    )
    assert options["temperature"] == 0.2
    assert options["top_p"] == 0.8
    assert options["seed"] == 11
    assert options["presence_penalty"] == 0.5


def test_options_omit_parameters_the_caller_did_not_send():
    options = build_options(BASE, num_ctx=4096, max_tokens=128)
    assert "temperature" not in options
    assert "stop" not in options


def test_a_single_stop_string_becomes_a_list():
    assert build_options({**BASE, "stop": "END"}, num_ctx=4096, max_tokens=8)["stop"] == ["END"]


def test_chat_response_is_openai_shaped():
    raw = {
        "model": "qwen3.5:9b",
        "message": {"role": "assistant", "content": "hello"},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 11,
        "eval_count": 3,
    }

    payload = chat_response_to_openai(raw, model="qwen3.5:9b", estimated_prompt_tokens=9)

    assert payload["object"] == "chat.completion"
    assert payload["id"].startswith("chatcmpl-")
    assert payload["model"] == "qwen3.5:9b"
    choice = payload["choices"][0]
    assert choice["index"] == 0
    assert choice["message"] == {"role": "assistant", "content": "hello"}
    assert choice["finish_reason"] == "stop"
    assert payload["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 3,
        "total_tokens": 14,
    }


def test_truncated_generation_reports_length():
    raw = {"message": {"role": "assistant", "content": "..."}, "done_reason": "length"}
    payload = chat_response_to_openai(raw, model="m", estimated_prompt_tokens=1)
    assert payload["choices"][0]["finish_reason"] == "length"


def test_tool_calls_are_translated_to_the_openai_shape():
    raw = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "geocode", "arguments": {"q": "Cairo"}}},
            ],
        },
        "done_reason": "stop",
    }

    payload = chat_response_to_openai(raw, model="m", estimated_prompt_tokens=5)

    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["type"] == "function"
    assert call["id"].startswith("call_")
    assert call["function"]["name"] == "geocode"
    assert json.loads(call["function"]["arguments"]) == {"q": "Cairo"}


def test_usage_falls_back_to_the_estimate_when_ollama_omits_counts():
    raw = {"message": {"role": "assistant", "content": "hi"}, "done_reason": "stop"}
    payload = chat_response_to_openai(raw, model="m", estimated_prompt_tokens=42)
    assert payload["usage"]["prompt_tokens"] == 42
    assert payload["usage"]["completion_tokens"] == 0


def test_embeddings_input_accepts_a_string():
    assert normalize_embeddings_input("hello") == ["hello"]


def test_embeddings_input_accepts_a_list_of_strings():
    assert normalize_embeddings_input(["a", "b"]) == ["a", "b"]


@pytest.mark.parametrize("value", [None, "", [], [1, 2, 3], {"a": 1}, [["a"]]])
def test_bad_embeddings_input_is_rejected(value):
    with pytest.raises(CloudiatorError):
        normalize_embeddings_input(value)


def test_embeddings_response_is_openai_shaped():
    payload = embeddings_response_to_openai(
        [[0.1, 0.2], [0.3, 0.4]], model="nomic-embed-text", prompt_tokens=7
    )
    assert payload["object"] == "list"
    assert [item["index"] for item in payload["data"]] == [0, 1]
    assert payload["data"][0]["object"] == "embedding"
    assert payload["model"] == "nomic-embed-text"
    assert payload["usage"] == {"prompt_tokens": 7, "total_tokens": 7}


def test_models_list_is_built_from_live_tags():
    payload = models_response_to_openai(
        [{"name": "qwen3.5:9b"}, {"model": "nomic-embed-text:latest"}, {}]
    )
    assert [item["id"] for item in payload["data"]] == ["qwen3.5:9b", "nomic-embed-text:latest"]
    assert all(item["object"] == "model" for item in payload["data"])


def test_latest_suffix_is_the_same_tag():
    assert normalize_tag("nomic-embed-text:latest") == "nomic-embed-text"
    assert normalize_tag("qwen3.5:9b") == "qwen3.5:9b"


@pytest.mark.parametrize(
    "model,expected",
    [
        ("qwen3.5:9b", -1),
        ("nomic-embed-text", -1),
        ("nomic-embed-text:latest", -1),
        ("gpt-oss:20b", 0),
        ("llama3.2:3b", 0),
    ],
)
def test_keep_alive_precedence(model, expected):
    client = OllamaClient(
        "http://127.0.0.1:11434", default_model="qwen3.5:9b", embed_model="nomic-embed-text"
    )
    assert client.keep_alive_for(model) == expected


async def test_every_ollama_call_sends_keep_alive():
    """Omitting keep_alive lets the env default unload the hot model."""
    import httpx

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "hi"}, "done_reason": "stop"}
        )

    client = OllamaClient(
        "http://127.0.0.1:11434",
        default_model="qwen3.5:9b",
        embed_model="nomic-embed-text",
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.chat("qwen3.5:9b", [{"role": "user", "content": "hi"}], options={})
        await client.set_keep_alive("gpt-oss:20b", 0)
    finally:
        await client.aclose()

    assert [payload["keep_alive"] for payload in seen] == [-1, 0]
    assert seen[0]["stream"] is False


async def test_a_missing_model_is_a_404_not_a_download():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'gpt-oss:20b' not found"})

    client = OllamaClient(
        "http://127.0.0.1:11434",
        default_model="qwen3.5:9b",
        embed_model="nomic-embed-text",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(CloudiatorError) as caught:
            await client.chat("gpt-oss:20b", [{"role": "user", "content": "hi"}], options={})
    finally:
        await client.aclose()

    assert caught.value.status_code == 404
    assert caught.value.code == "model_not_found"


async def test_a_dead_ollama_is_mini_offline():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = OllamaClient(
        "http://127.0.0.1:11434",
        default_model="qwen3.5:9b",
        embed_model="nomic-embed-text",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(CloudiatorError) as caught:
            await client.chat("qwen3.5:9b", [{"role": "user", "content": "hi"}], options={})
    finally:
        await client.aclose()

    assert caught.value.status_code == 503
    assert caught.value.code == "mini_offline"


async def test_exclusive_handover_polls_until_only_the_embedder_is_resident():
    """PLAN.md §8 rule 4: never assume the stop took effect."""
    import httpx

    responses = [
        {"models": [{"name": "gpt-oss:20b"}, {"name": "nomic-embed-text"}]},
        {"models": [{"name": "gpt-oss:20b"}]},
        {"models": [{"name": "nomic-embed-text"}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0) if responses else {"models": []})

    client = OllamaClient(
        "http://127.0.0.1:11434",
        default_model="qwen3.5:9b",
        embed_model="nomic-embed-text",
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.wait_until_only_embed_loaded(timeout=5)
    finally:
        await client.aclose()

    assert responses == []


async def test_handover_gives_up_rather_than_stacking_models():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]})

    client = OllamaClient(
        "http://127.0.0.1:11434",
        default_model="qwen3.5:9b",
        embed_model="nomic-embed-text",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(CloudiatorError) as caught:
            await client.wait_until_only_embed_loaded(timeout=0.2)
    finally:
        await client.aclose()

    assert caught.value.code == "metal_busy"
