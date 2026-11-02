"""Telling an answer from a question the caller asks instead.

The agent never makes anything up on a call. A caller's words become:

* an answer (the default), or
* a question that one of the script's pre-written FAQ answers covers, or
* a question it does not ("good question, I've noted it…").

Keywords decide first, on the Mini. Only when they miss does the local chat
model (Gemma, already loaded) pick the FAQ by key from the admin's list; it
returns a key or nothing, never text, and a slow or failed lookup falls back
to "noted". The words a caller hears are always the rendered, pre-written ones.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Mapping

from .engine import looks_like_question, match_faq, pick_route

log = logging.getLogger("cloudiator.voice.assistant")


class VoiceAssistant:
    def __init__(self, settings, *, ollama=None, scheduler=None) -> None:
        self.settings = settings
        self.ollama = ollama
        self.scheduler = scheduler

    async def intent(
        self, script: Mapping[str, Any], step: Mapping[str, Any], text: str, language: str
    ) -> dict[str, Any] | None:
        text = (text or "").strip()
        if not text or not looks_like_question(text, language):
            return None
        if pick_route(step, text, language):
            return None  # "is it new? yes, new" still routes as an answer
        key = match_faq(script, text, language)
        if key is None and script.get("faq") and self.settings.voice_llm_faq and self.ollama:
            key = await self._ask_model(script, text, language)
        return {"kind": "faq", "key": key} if key else {"kind": "off_script"}

    async def _ask_model(self, script: Mapping[str, Any], text: str, language: str) -> str | None:
        faqs = script.get("faq") or []
        # What each answer is about (its keywords, every language) and what it says.
        catalogue = "\n".join(
            f"- {item['key']}: about "
            + ", ".join(sorted({w.strip() for words in item["when"].values() for w in words if w.strip()}))
            + f". Answer: {item['say'].get(language) or next(iter(item['say'].values()))}"
            for item in faqs
        )
        messages = [
            {"role": "system", "content": (
                "You route a phone caller's question (Egyptian Arabic or English) to one pre-written "
                "answer. Pick the answer whose topic the question is about, even if worded differently "
                "(e.g. being hungry or eating relates to a food/meal answer). Reply with JSON only: "
                "{\"faq\": \"<key>\"}, or {\"faq\": null} if no answer is about that topic. "
                "Never write an answer yourself.\n"
                f"Answers:\n{catalogue}"
            )},
            {"role": "user", "content": text},
        ]
        try:
            async def call() -> dict[str, Any]:
                if self.scheduler is not None:
                    async with self.scheduler.chat_slot():
                        return await self.ollama.chat(
                            self.settings.default_model, messages,
                            options={"temperature": 0, "num_predict": 40, "num_ctx": 2048},
                            response_format="json_object", think=False,
                        )
                return await self.ollama.chat(
                    self.settings.default_model, messages,
                    options={"temperature": 0, "num_predict": 40, "num_ctx": 2048},
                    response_format="json_object", think=False,
                )

            data = await asyncio.wait_for(call(), self.settings.voice_llm_timeout_seconds)
            content = ((data or {}).get("message") or {}).get("content") or ""
            key = json.loads(content).get("faq")
        except Exception as exc:  # noqa: BLE001
            log.info("faq lookup by model skipped: %s", type(exc).__name__)
            return None
        return key if any(item["key"] == key for item in faqs) else None
