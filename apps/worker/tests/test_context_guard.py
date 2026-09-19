from __future__ import annotations

import pytest

from app.config import get_settings, reset_settings
from app.context_guard import assert_context_fits, estimate_prompt_tokens
from app.errors import ApiError


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDIATOR_ENV", "test")
    monkeypatch.setenv("NUM_CTX", "4096")
    reset_settings()


def test_over_context_raises() -> None:
    settings = get_settings()
    messages = [{"role": "user", "content": "word " * 5000}]
    with pytest.raises(ApiError) as exc:
        assert_context_fits(messages, max_tokens=512, settings=settings)
    assert exc.value.code == "context_length_exceeded"
    assert exc.value.status_code == 400
    assert "512" in exc.value.message
    assert "4096" in exc.value.message


def test_short_prompt_passes() -> None:
    settings = get_settings()
    messages = [{"role": "user", "content": "say hi"}]
    tokens = assert_context_fits(messages, max_tokens=16, settings=settings)
    assert tokens > 0
    assert tokens + 16 <= settings.num_ctx


def test_images_add_token_budget() -> None:
    settings = get_settings()
    text_only = [{"role": "user", "content": "describe"}]
    with_image = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
            ],
        }
    ]
    plain = estimate_prompt_tokens(text_only, settings)
    pictured = estimate_prompt_tokens(with_image, settings)
    assert pictured >= plain + settings.vision_tokens_per_image


def test_respects_custom_max_context() -> None:
    settings = get_settings()
    messages = [{"role": "user", "content": "hello there"}]
    with pytest.raises(ApiError) as exc:
        assert_context_fits(messages, max_tokens=20, settings=settings, max_context=8)
    assert exc.value.code == "context_length_exceeded"
