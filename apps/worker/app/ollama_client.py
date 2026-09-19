"""Ollama HTTP client. Always sends explicit keep_alive (PLAN.md §4)."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from app.config import Settings
from app.errors import mini_offline, model_not_found

log = logging.getLogger("cloudiator.ollama")

EMBED_PREFIXES = ("search_query:", "search_document:")


class OllamaClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.ollama_host.rstrip("/"),
            timeout=httpx.Timeout(settings.sync_deadline_seconds),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def keep_alive_for(self, model: str) -> int:
        if model in {self.settings.default_model, self.settings.embed_model}:
            return -1
        return 0

    async def chat(self, payload: dict[str, Any], *, stream: bool = False) -> dict[str, Any]:
        body = dict(payload)
        model = str(body.get("model") or self.settings.default_model)
        body["model"] = model
        body["stream"] = stream
        body["keep_alive"] = self.keep_alive_for(model)
        body.setdefault("think", self.settings.think)
        try:
            response = await self._client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise mini_offline() from exc
        if response.status_code == 404:
            raise model_not_found(model)
        if response.status_code >= 400:
            raise mini_offline(f"Ollama chat failed: HTTP {response.status_code} {response.text[:200]}")
        return response.json()

    async def chat_stream(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        body = dict(payload)
        model = str(body.get("model") or self.settings.default_model)
        body["model"] = model
        body["stream"] = True
        body["keep_alive"] = self.keep_alive_for(model)
        body.setdefault("think", self.settings.think)
        try:
            async with self._client.stream("POST", "/api/chat", json=body) as response:
                if response.status_code == 404:
                    raise model_not_found(model)
                if response.status_code >= 400:
                    await response.aread()
                    raise mini_offline(f"Ollama chat failed: HTTP {response.status_code}")
                async for line in response.aiter_lines():
                    if line:
                        yield json.loads(line)
        except httpx.HTTPError as exc:
            raise mini_offline() from exc

    async def embed(self, model: str, inputs: list[str]) -> dict[str, Any]:
        prefixed = [_prefix_embed(model, text, self.settings.embed_model) for text in inputs]
        body = {
            "model": model,
            "input": prefixed if len(prefixed) > 1 else prefixed[0],
            "keep_alive": self.keep_alive_for(model),
        }
        try:
            response = await self._client.post(
                "/api/embed",
                json=body,
                timeout=self.settings.embeddings_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise mini_offline() from exc
        if response.status_code == 404:
            # Older Ollama
            try:
                response = await self._client.post(
                    "/api/embeddings",
                    json={"model": model, "prompt": prefixed[0], "keep_alive": self.keep_alive_for(model)},
                    timeout=self.settings.embeddings_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise mini_offline() from exc
        if response.status_code == 404:
            raise model_not_found(model)
        if response.status_code >= 400:
            raise mini_offline(f"Ollama embeddings failed: HTTP {response.status_code}")
        return response.json()

    async def tags(self) -> list[dict[str, Any]]:
        try:
            response = await self._client.get("/api/tags", timeout=5.0)
        except httpx.HTTPError as exc:
            raise mini_offline() from exc
        if response.status_code >= 400:
            raise mini_offline(f"Ollama tags failed: HTTP {response.status_code}")
        data = response.json()
        return list(data.get("models") or [])

    async def ps(self) -> list[dict[str, Any]]:
        try:
            response = await self._client.get("/api/ps", timeout=2.0)
        except httpx.HTTPError:
            return []
        if response.status_code >= 400:
            return []
        data = response.json()
        return list(data.get("models") or [])

    async def loaded_names(self) -> list[str]:
        names: list[str] = []
        for model in await self.ps():
            name = model.get("name") or model.get("model")
            if name:
                names.append(str(name))
        return names

    async def warmup(self) -> None:
        """Pin the hot chat model and the embedder (keep_alive -1).

        Must not be awaited on the lifespan startup path: loading qwen3.5:9b
        can take longer than smoke/launchd health waits, and a thinking model
        with stream default-true can hang `/api/generate` past the timeout.
        """
        try:
            await self._client.post(
                "/api/generate",
                json={
                    "model": self.settings.default_model,
                    "prompt": "",
                    "keep_alive": -1,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 0},
                },
                timeout=180.0,
            )
        except Exception as exc:
            log.warning("hot model warmup failed: %s", exc)
        try:
            await self.embed(self.settings.embed_model, ["warmup"])
        except Exception as exc:
            log.warning("embed warmup failed: %s", exc)


def _prefix_embed(model: str, text: str, embed_model: str) -> str:
    if model != embed_model:
        return text
    stripped = text.lstrip()
    if stripped.startswith(EMBED_PREFIXES):
        return text
    return f"search_query: {text}"


def generative_names(loaded: list[str], embed_model: str) -> list[str]:
    embed_base = embed_model.split(":")[0]
    out: list[str] = []
    for name in loaded:
        base = name.split(":")[0]
        if embed_base in name or name.startswith(embed_model) or base == embed_base:
            continue
        out.append(name)
    return out
