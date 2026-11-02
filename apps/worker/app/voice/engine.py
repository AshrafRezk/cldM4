"""The step machine. A phone script is a state machine, not a tool loop.

Twilio posts one webhook per turn; each reply is TwiML that speaks every
non-gather step up to the next gather (or the end), so a script with no
gathers is one response. Replies are cached per (CallSid, step, attempt) so a
Twilio retry gets the same TwiML and never appends a second answer.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping
from urllib.parse import urlencode

from . import twiml
from .crm import render_commit, transcript_text
from .store import VoiceStore

log = logging.getLogger("cloudiator.voice")

SCRIPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
STEP_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
SOBJECT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
VOICE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 ()._-]{0,40}$")
E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
RESERVED_KEYS = {"transcript", "from", "to", "call_sid"}
MAX_STEPS = 50
INBOUND_STEP = "__inbound__"

FAIL_MESSAGES = {
    "ar": "عذراً، لم نتمكن من سماعك. سنعاود الاتصال بك لاحقاً.",
    "en": "Sorry, we could not hear you. We will call you back later.",
}


class ScriptInvalid(ValueError):
    def __init__(self, message: str, param: str | None = None) -> None:
        super().__init__(message)
        self.param = param


def validate_script(body: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a published script or raise ScriptInvalid. Pure function."""
    if not isinstance(body, Mapping):
        raise ScriptInvalid("The script must be a JSON object.")
    script_id = body.get("id")
    if not isinstance(script_id, str) or not SCRIPT_ID.match(script_id):
        raise ScriptInvalid("id must be 1-80 letters, digits, '-' or '_'.", "id")

    numbers = body.get("inbound_numbers") or []
    if not isinstance(numbers, list) or not all(isinstance(n, str) for n in numbers):
        raise ScriptInvalid("inbound_numbers must be a list of E.164 strings.", "inbound_numbers")
    numbers = [n.strip() for n in numbers if n.strip()]
    for number in numbers:
        if not E164.match(number):
            raise ScriptInvalid(f"{number!r} is not an E.164 number.", "inbound_numbers")

    languages = body.get("languages") or [body.get("language") or "en-US"]
    if (
        not isinstance(languages, list)
        or not languages
        or len(languages) > 4
        or not all(isinstance(lang, str) and LANGUAGE.match(lang) for lang in languages)
        or len(set(languages)) != len(languages)
    ):
        raise ScriptInvalid("languages must list 1-4 language tags like ar-EG, en-US.", "languages")

    raw_steps = body.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ScriptInvalid("steps must be a non-empty list.", "steps")
    if len(raw_steps) > MAX_STEPS:
        raise ScriptInvalid(f"A script may have at most {MAX_STEPS} steps.", "steps")

    steps: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, raw in enumerate(raw_steps):
        where = f"steps[{index}]"
        if not isinstance(raw, Mapping):
            raise ScriptInvalid(f"{where} must be an object.", where)
        key = raw.get("key")
        if not isinstance(key, str) or not STEP_KEY.match(key):
            raise ScriptInvalid(f"{where}.key must be an identifier.", f"{where}.key")
        if key in RESERVED_KEYS:
            raise ScriptInvalid(f"{where}.key {key!r} is reserved.", f"{where}.key")
        if key in keys:
            raise ScriptInvalid(f"Duplicate step key {key!r}.", f"{where}.key")
        keys.add(key)
        say = _localized(raw.get("say"), languages, f"{where}.say")
        nxt = raw.get("next")
        if nxt is not None and not isinstance(nxt, str):
            raise ScriptInvalid(f"{where}.next must be a step key or null.", f"{where}.next")
        on_fail = raw.get("on_fail", "continue")
        if on_fail not in ("continue", "hangup"):
            raise ScriptInvalid(f"{where}.on_fail must be continue or hangup.", f"{where}.on_fail")
        steps.append(
            {
                "key": key,
                "say": say,
                "gather": bool(raw.get("gather", False)),
                "timeout": _bounded_int(raw.get("timeout", 5), 1, 60, f"{where}.timeout"),
                "speech_timeout": str(raw.get("speech_timeout", "auto")),
                "max_attempts": _bounded_int(raw.get("max_attempts", 2), 1, 5, f"{where}.max_attempts"),
                "on_fail": on_fail,
                "next": nxt,
            }
        )

    for step in steps:
        if step["next"] is not None and step["next"] not in keys:
            raise ScriptInvalid(f"Step {step['key']!r} points at unknown step {step['next']!r}.", "steps")
    _reject_cycles(steps)

    commit = body.get("commit") or {"records": []}
    records = commit.get("records") if isinstance(commit, Mapping) else None
    if not isinstance(records, list):
        raise ScriptInvalid("commit.records must be a list.", "commit.records")
    seen: list[str] = []
    clean_records = []
    for index, record in enumerate(records):
        where = f"commit.records[{index}]"
        if not isinstance(record, Mapping):
            raise ScriptInvalid(f"{where} must be an object.", where)
        sobject = record.get("sobject")
        if not isinstance(sobject, str) or not SOBJECT.match(sobject):
            raise ScriptInvalid(f"{where}.sobject must be an sObject API name.", f"{where}.sobject")
        if sobject in seen:
            raise ScriptInvalid(f"{where}: one record per sObject type.", f"{where}.sobject")
        fields = record.get("fields")
        if not isinstance(fields, Mapping) or not all(
            isinstance(k, str) and SOBJECT.match(k) and isinstance(v, str) for k, v in fields.items()
        ):
            raise ScriptInvalid(f"{where}.fields must map field API names to text.", f"{where}.fields")
        after = record.get("after") or []
        if not isinstance(after, list) or any(parent not in seen for parent in after):
            raise ScriptInvalid(f"{where}.after must name records listed earlier.", f"{where}.after")
        seen.append(sobject)
        clean_records.append({"sobject": sobject, "fields": dict(fields), "after": list(after)})

    fail_say = body.get("fail_say")
    voices = body.get("voices") or {}
    if not isinstance(voices, Mapping) or not all(
        lang in languages and isinstance(name, str) and VOICE_NAME.match(name) for lang, name in voices.items()
    ):
        raise ScriptInvalid("voices maps a script language to a voice name.", "voices")

    return {
        "id": script_id,
        "display_name": str(body.get("display_name") or script_id),
        "language": languages[0],
        "languages": list(languages),
        # Per-language speaker for the browser call: a VoiceTut speaker name
        # (e.g. Hadeer, Mohammed) or, for the macOS fallback, a `say` voice.
        "voices": dict(voices),
        "voice": body.get("voice") or None,
        # macOS `say` voice for the browser call (e.g. Majed, Samantha).
        "local_voice": body.get("local_voice") or None,
        "inbound_numbers": numbers,
        "active": bool(body.get("active", True)),
        "fail_say": _localized(fail_say, languages, "fail_say") if fail_say else None,
        "steps": steps,
        "commit": {"records": clean_records},
    }


def _localized(value: Any, languages: list[str], param: str) -> dict[str, str]:
    """Text for every script language: a plain string is used for all of them."""
    if isinstance(value, str) and value.strip():
        return {lang: value.strip() for lang in languages}
    if isinstance(value, Mapping):
        out = {}
        for lang in languages:
            text = value.get(lang)
            if not isinstance(text, str) or not text.strip():
                raise ScriptInvalid(f"{param} needs text for {lang}.", param)
            out[lang] = text.strip()
        return out
    raise ScriptInvalid(f"{param} must be text, or text per language.", param)


def text_for(value: Any, language: str) -> str:
    """Scripts published before languages existed store plain strings."""
    if isinstance(value, Mapping):
        return value.get(language) or next(iter(value.values()))
    return value


def _bounded_int(value: Any, low: int, high: int, param: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ScriptInvalid(f"{param} must be an integer from {low} to {high}.", param)
    return value


def _reject_cycles(steps: list[dict[str, Any]]) -> None:
    following = {step["key"]: step["next"] for step in steps}
    for start in following:
        seen = set()
        key: str | None = start
        while key is not None:
            if key in seen:
                raise ScriptInvalid(f"Steps loop back on themselves at {key!r}.", "steps")
            seen.add(key)
            key = following[key]


class VoiceEngine:
    """Channel-neutral step machine.

    Every webhook returns a Reply: an ordered list of verbs, each one of
    {"say": text}, {"gather": {...}}, or {"hangup": True}. Twilio renders it to
    TwiML (`render_twiml`); the browser call renders it to text plus audio.
    The cache stores the Reply, so a retry on either channel replays exactly.
    """

    def __init__(self, store: VoiceStore, *, public_base_url: str, ttl_days: float) -> None:
        self.store = store
        self.base_url = public_base_url.rstrip("/")
        self.ttl_days = ttl_days

    def gather_url(self, step: str, attempt: int) -> str:
        return f"{self.base_url}/v1/voice/twilio/gather?" + urlencode(
            {"step": step, "attempt": attempt}
        )

    # Calls -------------------------------------------------------------------

    def on_inbound(self, *, call_sid: str, from_number: str, to_number: str) -> Reply:
        """Twilio: the dialled number picks the script."""
        cached = self.store.reply_for(call_sid, INBOUND_STEP, 0)
        if cached is not None:
            return cached
        self.store.purge_expired(self.ttl_days)
        found = self.store.script_for_number(to_number)
        if found is None:
            log.warning("inbound call to an unrouted number; hanging up")
            return _reply(None, [{"hangup": True}])
        tenant_id, version, script = found
        return self._start(tenant_id, version, script, call_sid, from_number, to_number, script["language"])

    def start_call(
        self,
        *,
        tenant_id: str,
        script_id: str,
        call_sid: str,
        from_label: str,
        language: str | None = None,
    ) -> Reply | None:
        """Browser call: the call link already names tenant and script."""
        cached = self.store.reply_for(call_sid, INBOUND_STEP, 0)
        if cached is not None:
            return cached
        self.store.purge_expired(self.ttl_days)
        found = self.store.script_by_id(tenant_id, script_id)
        if found is None:
            return None
        version, script = found
        language = language or script["language"]
        if language not in languages_of(script):
            raise ScriptInvalid(f"This script does not speak {language}.", "lang")
        return self._start(
            tenant_id, version, script, call_sid, from_label, f"web:{script_id}", language
        )

    def _start(self, tenant_id, version, script, call_sid, from_number, to_number, language) -> Reply:
        session = self.store.create_session(
            tenant_id=tenant_id,
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            script=script,
            script_version=version,
            first_step=script["steps"][0]["key"],
            language=language,
        )
        log.info("voice session %s started on script %s (%s)", session["id"], script["id"], language)
        reply = self._advance(session, script["steps"][0]["key"])
        self.store.save_reply(call_sid, INBOUND_STEP, 0, reply)
        return reply

    def on_gather(self, *, call_sid: str, step: str, attempt: int, speech: str) -> Reply:
        cached = self.store.reply_for(call_sid, step, attempt)
        if cached is not None:
            return cached
        session = self.store.session_by_call(call_sid)
        if (
            session is None
            or session["status"] != "in_progress"
            or session["current_step"] != step
            or session["attempt"] != attempt
        ):
            # Out of order or forged-but-signed: never continue the script.
            return _reply(None, [{"hangup": True}])

        script = session["definition"]
        current = _step(script, step)
        text = speech.strip()
        turns = list(session["turns"])
        answers = dict(session["answers"])

        if text:
            turns.append({"role": "caller", "text": text})
            answers[step] = text
            self.store.update_session(session["id"], turns=turns, answers=answers)
            reply = self._advance({**session, "turns": turns, "answers": answers}, current["next"])
        elif attempt < current["max_attempts"]:
            self.store.update_session(session["id"], attempt=attempt + 1)
            reply = _reply(
                script,
                [self._gather_verb({**session, "attempt": attempt + 1}, current)],
                session_language(session),
            )
        elif current["on_fail"] == "continue":
            answers[step] = ""
            self.store.update_session(session["id"], answers=answers)
            reply = self._advance({**session, "answers": answers}, current["next"])
        else:
            language = session_language(session)
            message = (
                text_for(script["fail_say"], language)
                if script.get("fail_say")
                else FAIL_MESSAGES["ar" if language.lower().startswith("ar") else "en"]
            )
            turns.append({"role": "agent", "text": message})
            self.store.update_session(
                session["id"], status="abandoned", current_step=None, turns=turns
            )
            log.info("voice session %s abandoned at %s", session["id"], step)
            reply = _reply(script, [{"say": message, "key": "__fail__"}, {"hangup": True}], language)

        self.store.save_reply(call_sid, step, attempt, reply)
        return reply

    def on_recording(self, *, call_sid: str, recording_url: str) -> None:
        session = self.store.session_by_call(call_sid)
        if session is not None and recording_url:
            self.store.update_session(session["id"], recording_url=recording_url)

    # Rendering ---------------------------------------------------------------

    def render_twiml(self, reply: Reply) -> str:
        verbs = []
        for verb in reply["verbs"]:
            if "say" in verb:
                verbs.append(twiml.say(verb["say"], voice=reply.get("voice"), language=reply.get("language")))
            elif "gather" in verb:
                g = verb["gather"]
                verbs.append(
                    twiml.gather(
                        twiml.say(g["prompt"], voice=reply.get("voice"), language=reply.get("language")),
                        action=self.gather_url(g["step"], g["attempt"]),
                        language=reply.get("language"),
                        timeout=g["timeout"],
                        speech_timeout=g["speech_timeout"],
                    )
                )
            elif verb.get("hangup"):
                verbs.append(twiml.hangup())
        return twiml.response(*verbs)

    def _advance(self, session: dict[str, Any], key: str | None) -> Reply:
        """Speak non-gather steps from `key` until a gather or the end."""
        script = session["definition"]
        language = session_language(session)
        turns = list(session["turns"])
        verbs: list[dict[str, Any]] = []
        while key is not None:
            step = _step(script, key)
            if step["gather"]:
                self.store.update_session(session["id"], current_step=key, attempt=1)
                verbs.append(self._gather_verb({**session, "turns": turns, "attempt": 1}, step))
                return _reply(script, verbs, language)
            text = text_for(step["say"], language)
            turns.append({"role": "agent", "text": text})
            verbs.append({"say": text, "key": step["key"]})
            key = step["next"]

        commit = render_commit(
            script.get("commit") or {"records": []},
            answers=session["answers"],
            transcript=transcript_text(turns),
            call={
                "from": session.get("from_number") or "",
                "to": session.get("to_number") or "",
                "call_sid": session["call_sid"],
            },
        )
        self.store.update_session(
            session["id"],
            turns=turns,
            status="ready_to_commit",
            current_step=None,
            commit_doc=commit,
        )
        log.info("voice session %s ready to commit", session["id"])
        verbs.append({"hangup": True})
        return _reply(script, verbs, language)

    def _gather_verb(self, session: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        """The gather prompt is a turn too; it is recorded with any says before it."""
        prompt = text_for(step["say"], session_language(session))
        turns = list(session["turns"]) + [{"role": "agent", "text": prompt}]
        self.store.update_session(session["id"], turns=turns)
        return {
            "gather": {
                "step": step["key"],
                "attempt": session["attempt"],
                "prompt": prompt,
                "timeout": step["timeout"],
                "speech_timeout": step["speech_timeout"],
            }
        }


Reply = dict[str, Any]


def _reply(
    script: Mapping[str, Any] | None, verbs: list[dict[str, Any]], language: str | None = None
) -> Reply:
    script = script or {}
    language = language or script.get("language")
    return {
        "script_id": script.get("id"),
        "language": language,
        "voice": script.get("voice"),
        "local_voice": (script.get("voices") or {}).get(language) or script.get("local_voice"),
        "verbs": verbs,
    }


def languages_of(script: Mapping[str, Any]) -> list[str]:
    return list(script.get("languages") or [script.get("language") or "en-US"])


def session_language(session: Mapping[str, Any]) -> str:
    return session.get("language") or session["definition"].get("language") or "en-US"


def _step(script: Mapping[str, Any], key: str) -> dict[str, Any]:
    for step in script["steps"]:
        if step["key"] == key:
            return step
    raise KeyError(key)
