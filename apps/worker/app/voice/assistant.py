"""Telling an answer from a question the caller asks instead.

The agent never invents facts on a call. A caller's words become:

* an answer (the default), or
* a question that one of the script's pre-written FAQ answers covers, or
* a question or concern answered from the script's knowledge payload (Gemma
  may paraphrase only what is written there), or
* a question it does not ("good question, I've noted it…").

Keywords decide first, on the Mini. Only when they miss does the local chat
model (Gemma, already loaded) pick an FAQ key or write a short grounded reply.
A slow or failed lookup falls back to "noted".
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Mapping

from .engine import (
    knowledge_text,
    looks_like_concern,
    looks_like_question,
    match_faq,
    pick_route,
)

log = logging.getLogger("cloudiator.voice.assistant")

_UNSAFE = re.compile(
    r"(?i)\b(dose|dosage|mg\b|ml\b|prescribe|prescription|جرعه|جرعة|مليجرام)\b"
)


class VoiceAssistant:
    def __init__(self, settings, *, ollama=None, scheduler=None) -> None:
        self.settings = settings
        self.ollama = ollama
        self.scheduler = scheduler

    async def intent(
        self, script: Mapping[str, Any], step: Mapping[str, Any], text: str, language: str
    ) -> dict[str, Any] | None:
        text = (text or "").strip()
        if not text:
            return None
        ask = looks_like_question(text, language) or looks_like_concern(text, language)
        if not ask:
            return None
        if pick_route(step, text, language):
            return None  # "is it new? yes, new" still routes as an answer
        key = match_faq(script, text, language)
        if key is None and script.get("faq") and self.settings.voice_llm_faq and self.ollama:
            key = await self._ask_model(script, text, language)
        if key:
            return {"kind": "faq", "key": key}
        knowledge = knowledge_text(script, language)
        if knowledge and self.settings.voice_llm_faq and self.ollama:
            answer = await self._answer_from_knowledge(text, language, knowledge)
            if answer:
                return {"kind": "knowledge", "answer": answer}
        return {"kind": "off_script"}

    async def _chat(self, messages: list[dict[str, str]], *, num_predict: int) -> str:
        async def call() -> dict[str, Any]:
            if self.scheduler is not None:
                async with self.scheduler.chat_slot():
                    return await self.ollama.chat(
                        self.settings.default_model, messages,
                        options={"temperature": 0, "num_predict": num_predict, "num_ctx": 2048},
                        response_format="json_object", think=False,
                    )
            return await self.ollama.chat(
                self.settings.default_model, messages,
                options={"temperature": 0, "num_predict": num_predict, "num_ctx": 2048},
                response_format="json_object", think=False,
            )

        data = await asyncio.wait_for(call(), self.settings.voice_llm_timeout_seconds)
        return ((data or {}).get("message") or {}).get("content") or ""

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
            content = await self._chat(messages, num_predict=40)
            key = json.loads(content).get("faq")
        except Exception as exc:  # noqa: BLE001
            log.info("faq lookup by model skipped: %s", type(exc).__name__)
            return None
        return key if any(item["key"] == key for item in faqs) else None

    async def _answer_from_knowledge(self, text: str, language: str, knowledge: str) -> str | None:
        """At most two short sentences, only from the knowledge payload."""
        arabic = language.lower().startswith("ar")
        style = (
            "Reply in Egyptian Colloquial Arabic (عامية مصرية), at most two short sentences."
            if arabic
            else "Reply in clear spoken English, at most two short sentences."
        )
        messages = [
            {"role": "system", "content": (
                "You answer a phone caller's question or concern using ONLY the knowledge text below. "
                "If the knowledge does not cover it, reply with JSON {\"answer\": null}. "
                "If it does, reply with JSON {\"answer\": \"...\"}. "
                f"{style} "
                "Do not invent doses, prices, schedules, policies, or medical advice that is not written "
                "in the knowledge. Never invent a phone number or URL.\n\n"
                f"Knowledge:\n{knowledge}"
            )},
            {"role": "user", "content": text},
        ]
        try:
            content = await self._chat(messages, num_predict=120)
            answer = json.loads(content).get("answer")
        except Exception as exc:  # noqa: BLE001
            log.info("knowledge answer skipped: %s", type(exc).__name__)
            return None
        if not isinstance(answer, str):
            return None
        answer = " ".join(answer.strip().split())
        if not answer or len(answer) > 400 or _UNSAFE.search(answer):
            return None
        # Reject answers that introduce digits/URLs not present in the knowledge.
        if re.search(r"https?://|www\.", answer) and "http" not in knowledge.lower() and "www." not in knowledge.lower():
            return None
        return answer
