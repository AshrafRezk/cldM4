"""Ollama client.

Two rules this module exists to enforce:

1. **Every** call sends an explicit `keep_alive` (PLAN.md §4). `-1` for the hot
   chat model and the embedder, `0` for everything else. Omitting it lets the
   env default unload the hot model after 30 quiet minutes, and the first
   Salesforce call of the morning then spends 5-15s of its 120s budget on a
   cold load.
2. The exclusive-slot handover never assumes `stop` took effect — it polls
   `/api/ps` until nothing but the embedder remains (PLAN.md §8 rule 4).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .errors import CloudiatorError, mini_offline, model_not_found

log = logging.getLogger("cloudiator.ollama")


def normalize_tag(name: str) -> str:
    """`nomic-embed-text` and `nomic-embed-text:latest` are the same model."""
    return name[: -len(":latest")] if name.endswith(":latest") else name


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        *,
        default_model: str,
        embed_model: str,
        chat_timeout: float = 90.0,
        embeddings_timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.embed_model = embed_model
        self.chat_timeout = chat_timeout
        self.embeddings_timeout = embeddings_timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._tags_cache: list[dict[str, Any]] | None = None
        self._tags_cached_at = 0.0

    # ---- plumbing ---------------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                transport=self._transport,
                timeout=httpx.Timeout(connect=2.0, read=self.chat_timeout, write=10.0, pool=2.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def keep_alive_for(self, model: str) -> int:
        if normalize_tag(model) in (
            normalize_tag(self.default_model),
            normalize_tag(self.embed_model),
        ):
            return -1
        return 0

    async def _post(self, path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        if "keep_alive" not in payload:
            raise AssertionError(f"keep_alive must be explicit on every Ollama call ({path})")
        client = self._ensure_client()
        try:
            response = await client.post(path, json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise CloudiatorError(
                504,
                "not_supported",
                f"Ollama did not respond within {timeout:.0f}s.",
                error_type="server_error",
            ) from exc
        except httpx.HTTPError as exc:
            raise mini_offline(f"Ollama at {self.base_url} is unreachable.") from exc
        return self._parse(response, payload.get("model"))

    async def _get(self, path: str, *, timeout: float = 5.0) -> dict[str, Any]:
        client = self._ensure_client()
        try:
            response = await client.get(path, timeout=timeout)
        except httpx.HTTPError as exc:
            raise mini_offline(f"Ollama at {self.base_url} is unreachable.") from exc
        return self._parse(response, None)

    def _parse(self, response: httpx.Response, model: str | None) -> dict[str, Any]:
        if response.status_code == 404 and model:
            raise model_not_found(model)
        if response.status_code >= 400:
            detail = response.text[:300]
            raise CloudiatorError(
                502,
                "not_supported",
                f"Ollama returned {response.status_code}: {detail}",
                error_type="server_error",
            )
        try:
            return response.json()
        except ValueError as exc:
            raise CloudiatorError(
                502, "not_supported", "Ollama returned a non-JSON body.", error_type="server_error"
            ) from exc

    # ---- inference --------------------------------------------------------

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": self.keep_alive_for(model),
        }
        if tools:
            payload["tools"] = tools
        if response_format == "json_object":
            payload["format"] = "json"
        return await self._post("/api/chat", payload, timeout=self.chat_timeout)

    async def embeddings(self, model: str, inputs: list[str]) -> list[list[float]]:
        payload = {
            "model": model,
            "input": inputs,
            "keep_alive": self.keep_alive_for(model),
        }
        data = await self._post("/api/embed", payload, timeout=self.embeddings_timeout)
        vectors = data.get("embeddings")
        if vectors is None and "embedding" in data:
            vectors = [data["embedding"]]
        if not vectors:
            raise CloudiatorError(
                502,
                "not_supported",
                "Ollama returned no embeddings.",
                error_type="server_error",
            )
        return vectors

    # ---- model state ------------------------------------------------------

    async def tags(self) -> list[dict[str, Any]]:
        data = await self._get("/api/tags")
        return data.get("models", [])

    async def tags_cached(self, ttl: float = 30.0) -> list[dict[str, Any]]:
        """Short TTL so a chat request can check "is this model on disk?" cheaply.

        Advertising or accepting a model that is not on disk starts a multi-GB
        download inside an HTTP request (PLAN.md §7).
        """
        now = asyncio.get_running_loop().time()
        if self._tags_cache is not None and now - self._tags_cached_at < ttl:
            return self._tags_cache
        tags = await self.tags()
        self._tags_cache = tags
        self._tags_cached_at = now
        return tags

    def invalidate_tags_cache(self) -> None:
        self._tags_cache = None

    async def installed_tags(self) -> set[str]:
        names: set[str] = set()
        for tag in await self.tags_cached():
            name = tag.get("name") or tag.get("model")
            if name:
                names.add(normalize_tag(name))
        return names

    async def ps(self) -> list[dict[str, Any]]:
        data = await self._get("/api/ps")
        return data.get("models", [])

    async def loaded_models(self) -> list[str]:
        return [normalize_tag(m.get("name") or m.get("model") or "") for m in await self.ps()]

    async def loaded_generative_models(self) -> list[str]:
        embed = normalize_tag(self.embed_model)
        return [name for name in await self.loaded_models() if name and name != embed]

    async def set_keep_alive(self, model: str, keep_alive: int) -> None:
        """Load (keep_alive=-1) or unload (keep_alive=0) without generating."""
        payload = {"model": model, "prompt": "", "keep_alive": keep_alive}
        await self._post("/api/generate", payload, timeout=60.0)

    async def unload(self, model: str) -> None:
        await self.set_keep_alive(model, 0)

    async def unload_hot_model(self) -> None:
        await self.unload(self.default_model)

    async def reload_hot_model(self) -> None:
        await self.set_keep_alive(self.default_model, -1)

    async def warm_embedder(self) -> None:
        await self.set_keep_alive(self.embed_model, -1)

    async def unload_all_generative(self) -> None:
        for name in await self.loaded_generative_models():
            try:
                await self.unload(name)
            except CloudiatorError:
                log.warning("best-effort unload of %s failed", name)

    async def wait_until_only_embed_loaded(self, timeout: float = 30.0) -> None:
        """Poll /api/ps. Never assume a stop took effect (PLAN.md §8 rule 4)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            generative = await self.loaded_generative_models()
            if not generative:
                return
            if loop.time() >= deadline:
                raise CloudiatorError(
                    503,
                    "metal_busy",
                    f"Models {generative} are still resident after {timeout:.0f}s; refusing to "
                    "load an exclusive model on top of them.",
                    error_type="server_error",
                    retry_after=10,
                )
            await asyncio.sleep(0.5)
