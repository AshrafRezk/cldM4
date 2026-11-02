"""The step machine. A phone script is a state machine, not a tool loop.

Twilio posts one webhook per turn; each reply is TwiML that speaks every
non-gather step up to the next gather (or the end), so a script with no
gathers is one response. Every prompt gets a per-call `turn` number (a route
can ask the same question twice, attempt 1 both times), and replies are cached
per (CallSid, step#turn, attempt) so a
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
RESERVED_KEYS = {"transcript", "from", "to", "call_sid", "agent"}
MAX_STEPS = 50
INBOUND_STEP = "__inbound__"

# Said to a caller waiting in line, repeated over the hold music. The opening
# adapts to the script: the persona's name ({{agent}}) and the company variable.
HOLD_OPENINGS = {
    "ar": {
        (True, True): "أهلاً بيك، معاك {{agent}} من {company}.",
        (True, False): "أهلاً بيك، معاك {{agent}}.",
        (False, True): "أهلاً بيك في {company}.",
        (False, False): "أهلاً بيك.",
    },
    "en": {
        (True, True): "Hi, this is {{agent}} from {company}.",
        (True, False): "Hi, this is {{agent}}.",
        (False, True): "Thanks for calling {company}.",
        (False, False): "Thanks for calling.",
    },
}
HOLD_MESSAGES = {
    "ar": "أنا بخلّص مكالمة دلوقتي وهبدأ معاك على طول. متقفلش من فضلك، وشكراً على صبرك!",
    "en": "I'm just finishing a call and will be with you right away. Please don't hang up, and thank you for your patience!",
}

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

    variables = _variables(body.get("variables"), languages)
    personas = _personas(body.get("personas"), languages)
    passthrough = {"agent"} if personas else set()

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
        say = _fill(_localized(raw.get("say"), languages, f"{where}.say"), variables, f"{where}.say", passthrough)
        nxt = raw.get("next")
        if nxt is not None and not isinstance(nxt, str):
            raise ScriptInvalid(f"{where}.next must be a step key or null.", f"{where}.next")
        on_fail = raw.get("on_fail", "continue")
        if on_fail not in ("continue", "hangup"):
            raise ScriptInvalid(f"{where}.on_fail must be continue or hangup.", f"{where}.on_fail")
        gather = bool(raw.get("gather", False))
        routes = _routes(raw.get("routes"), languages, f"{where}.routes")
        if routes and not gather:
            raise ScriptInvalid(f"{where}: only a question (gather) can route on the answer.", f"{where}.routes")
        steps.append(
            {
                "key": key,
                "say": say,
                "gather": gather,
                "routes": routes,
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
        for route in step["routes"]:
            if route["next"] is not None and route["next"] not in keys:
                raise ScriptInvalid(
                    f"Step {step['key']!r} routes to unknown step {route['next']!r}.", "steps"
                )
    clash = set(variables) & keys
    if clash:
        raise ScriptInvalid(f"Variable {sorted(clash)[0]!r} has the same name as a step.", "variables")
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
        # Variables are fixed per script: resolve them now, in the CRM language.
        fields = {name: _fill_text(value, variables, crm_language(languages)) for name, value in fields.items()}
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
        "variables": variables,
        # Agents a caller can choose ("Hello, this is {{agent}} from {{company}}").
        "personas": personas,
        # A short tone after each question tells the caller when to speak.
        "beep": bool(body.get("beep", True)),
        # Soft generated music under the repeating hold message while waiting in line.
        "hold_music": bool(body.get("hold_music", True)),
        "fail_say": _fill(_localized(fail_say, languages, "fail_say"), variables, "fail_say", passthrough) if fail_say else None,
        "hold_say": (
            _fill(_localized(body["hold_say"], languages, "hold_say"), variables, "hold_say", passthrough)
            if body.get("hold_say") else None
        ),
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


VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
MAX_ROUTES = 10
MAX_CALLER_TURNS = 40


def _variables(raw: Any, languages: list[str]) -> dict[str, dict[str, str]]:
    """{"company": "Merck"} or {"company": {"ar-EG": "ميرك", "en-US": "Merck"}}.
    A plain string is used in every language."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping) or len(raw) > 30:
        raise ScriptInvalid("variables must be an object of up to 30 names.", "variables")
    out = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not STEP_KEY.match(name) or name in RESERVED_KEYS:
            raise ScriptInvalid(f"Variable name {name!r} is not allowed.", "variables")
        out[name] = _localized(value, languages, f"variables.{name}")
    return out


def _fill_text(text: str, variables: Mapping[str, Mapping[str, str]], language: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return variables[name][language] if name in variables else match.group(0)

    return VARIABLE.sub(replace, text)


def _fill(
    texts: dict[str, str],
    variables: Mapping[str, Mapping[str, str]],
    param: str,
    passthrough: set[str] = frozenset(),
) -> dict[str, str]:
    """Spoken lines may only use declared variables; a typo is a publish error,
    not a caller hearing "{{compnay}}". `{{agent}}` stays until a caller picks
    a persona."""
    out = {}
    for language, text in texts.items():
        for name in VARIABLE.findall(text):
            if name not in variables and name not in passthrough:
                raise ScriptInvalid(f"{param} uses {{{{{name}}}}}, which is not in variables.", param)
        out[language] = _fill_text(text, variables, language)
    return out


def _personas(raw: Any, languages: list[str]) -> list[dict[str, Any]]:
    """[{"id": "mariam", "name": {"ar-EG": "مريم", "en-US": "Mariam"}, "voice": "Mariam"}]

    `voice` is a speaker name, or one per language. The caller picks a persona
    on the call page; `{{agent}}` becomes their name in every line."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 6:
        raise ScriptInvalid("personas must be a list of up to 6.", "personas")
    out, ids = [], set()
    for index, persona in enumerate(raw):
        where = f"personas[{index}]"
        if not isinstance(persona, Mapping):
            raise ScriptInvalid(f"{where} must be an object.", where)
        pid = persona.get("id")
        if not isinstance(pid, str) or not STEP_KEY.match(pid) or pid in ids:
            raise ScriptInvalid(f"{where}.id must be a unique identifier.", f"{where}.id")
        ids.add(pid)
        voice = persona.get("voice")
        voices = {lang: voice for lang in languages} if isinstance(voice, str) else voice
        if not isinstance(voices, Mapping) or not all(
            lang in languages and isinstance(v, str) and VOICE_NAME.match(v) for lang, v in voices.items()
        ):
            raise ScriptInvalid(f"{where}.voice must be a voice name, or one per language.", f"{where}.voice")
        out.append({"id": pid, "name": _localized(persona.get("name"), languages, f"{where}.name"),
                    "voices": dict(voices)})
    return out


def find_persona(script: Mapping[str, Any], persona_id: str | None) -> dict[str, Any] | None:
    personas = script.get("personas") or []
    if not personas:
        return None
    if persona_id is None:
        return personas[0]
    return next((p for p in personas if p["id"] == persona_id), None)


def speak(value: Any, language: str, persona: Mapping[str, Any] | None) -> str:
    """A line as one caller hears it: their language, their agent's name."""
    text = text_for(value, language)
    if persona is None:
        return text
    name = persona["name"].get(language) or next(iter(persona["name"].values()))
    return VARIABLE.sub(lambda m: name if m.group(1) == "agent" else m.group(0), text)


def crm_language(languages: list[str]) -> str:
    """CRM fields take the English value of a variable when there is one."""
    return next((lang for lang in languages if lang.startswith("en")), languages[0])


def _routes(raw: Any, languages: list[str], param: str) -> list[dict[str, Any]]:
    """[{"when": ["new", "جديد"] | {"ar-EG": [...], "en-US": [...]}, "next": "q_new", "value": "New"}]

    The first route whose keyword appears in the caller's answer wins; no match
    falls through to the step's `next`. `value` (optional) is stored as the
    answer instead of the caller's words, e.g. a picklist value for the CRM."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ROUTES:
        raise ScriptInvalid(f"routes must be a list of up to {MAX_ROUTES}.", param)
    out = []
    for index, route in enumerate(raw):
        where = f"{param}[{index}]"
        if not isinstance(route, Mapping):
            raise ScriptInvalid(f"{where} must be an object.", where)
        when = route.get("when")
        if isinstance(when, list):
            when = {lang: when for lang in languages}
        if not isinstance(when, Mapping) or not when:
            raise ScriptInvalid(f"{where}.when must list keywords.", f"{where}.when")
        keywords = {}
        for lang, words in when.items():
            if lang not in languages or not isinstance(words, list) or not words or not all(
                isinstance(w, str) and w.strip() for w in words
            ):
                raise ScriptInvalid(f"{where}.when needs keywords per script language.", f"{where}.when")
            keywords[lang] = [normalize_answer(w) for w in words]
        nxt = route.get("next")
        if nxt is not None and not isinstance(nxt, str):
            raise ScriptInvalid(f"{where}.next must be a step key or null.", f"{where}.next")
        value = route.get("value")
        if value is not None and not isinstance(value, str):
            raise ScriptInvalid(f"{where}.value must be text.", f"{where}.value")
        out.append({"when": keywords, "next": nxt, "value": value})
    return out


_ARABIC_MARKS = re.compile(r"[\u064B-\u0652\u0670\u0640]")  # harakat, dagger alef, tatweel
_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_NOT_WORD = re.compile(r"[^\w]+")


def normalize_answer(text: str) -> str:
    """Fold case, Arabic spelling variants, diacritics, and punctuation so a
    keyword like "أيوه" matches whisper's "ايوة"."""
    text = _ARABIC_MARKS.sub("", text.lower()).translate(_ARABIC_FOLD)
    return " " + " ".join(_NOT_WORD.sub(" ", text).split()) + " "


def clean_answer(text: str) -> str:
    """Whisper ends sentences with punctuation; a name or phone field should
    not ("أشرف رزق." -> "أشرف رزق"). The transcript keeps the original."""
    return text.strip().rstrip(".,،؛;:!?؟…").strip()


def pick_route(step: Mapping[str, Any], answer: str, language: str) -> dict[str, Any] | None:
    heard = normalize_answer(answer)
    for route in step.get("routes") or []:
        for keyword in route["when"].get(language) or []:
            if keyword.strip() and keyword.strip() in heard:
                return route
    return None


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
    """A loop through a question is fine (each pass waits for the caller, e.g.
    "sorry, was that new or existing?"). A loop of announcements only would
    talk forever, so that is the one that is refused."""
    by_key = {step["key"]: step for step in steps}
    for start in by_key:
        seen = set()
        key: str | None = start
        while key is not None and not by_key[key]["gather"]:
            if key in seen:
                raise ScriptInvalid(f"Announcements loop back on themselves at {key!r}.", "steps")
            seen.add(key)
            key = by_key[key]["next"]


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

    def gather_url(self, step: str, attempt: int, turn: int | None = None) -> str:
        params = {"step": step, "attempt": attempt}
        if turn is not None:
            params["turn"] = turn
        return f"{self.base_url}/v1/voice/twilio/gather?" + urlencode(params)

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
        persona: str | None = None,
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
        chosen = find_persona(script, persona)
        if persona is not None and chosen is None:
            raise ScriptInvalid(f"This script has no persona {persona!r}.", "persona")
        return self._start(
            tenant_id, version, script, call_sid, from_label, f"web:{script_id}", language,
            chosen["id"] if chosen else None,
        )

    def _start(
        self, tenant_id, version, script, call_sid, from_number, to_number, language, persona=None
    ) -> Reply:
        session = self.store.create_session(
            tenant_id=tenant_id,
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            script=script,
            script_version=version,
            first_step=script["steps"][0]["key"],
            language=language,
            persona=persona,
        )
        log.info("voice session %s started on script %s (%s)", session["id"], script["id"], language)
        reply = self._advance(session, script["steps"][0]["key"])
        self.store.save_reply(call_sid, INBOUND_STEP, 0, reply)
        return reply

    def on_gather(
        self, *, call_sid: str, step: str, attempt: int, speech: str, turn: int | None = None
    ) -> Reply:
        cache_step = f"{step}#{turn}" if turn is not None else step
        cached = self.store.reply_for(call_sid, cache_step, attempt)
        if cached is not None:
            return cached
        session = self.store.session_by_call(call_sid)
        if (
            session is None
            or session["status"] != "in_progress"
            or session["current_step"] != step
            or session["attempt"] != attempt
            or (turn is not None and (session.get("turn") or 0) != turn)
        ):
            # Out of order or forged-but-signed: never continue the script.
            return _reply(None, [{"hangup": True}])

        script = session["definition"]
        current = _step(script, step)
        text = speech.strip()
        turns = list(session["turns"])
        answers = dict(session["answers"])

        if sum(1 for t in turns if t["role"] == "caller") >= MAX_CALLER_TURNS:
            # A route loop that never resolves must not keep a caller (and the line) forever.
            text, current = "", {**current, "max_attempts": attempt, "on_fail": "hangup"}
        if text:
            turns.append({"role": "caller", "text": text})
            route = pick_route(current, text, session_language(session))
            answers[step] = route["value"] if route and route.get("value") else clean_answer(text)
            self.store.update_session(session["id"], turns=turns, answers=answers)
            following = route["next"] if route else current["next"]
            reply = self._advance({**session, "turns": turns, "answers": answers}, following)
        elif attempt < current["max_attempts"]:
            next_turn = (session.get("turn") or 0) + 1
            self.store.update_session(session["id"], attempt=attempt + 1, turn=next_turn)
            reply = _reply(
                script,
                [self._gather_verb({**session, "attempt": attempt + 1, "turn": next_turn}, current)],
                session_language(session),
                session_persona(session),
            )
        elif current["on_fail"] == "continue":
            answers[step] = ""
            self.store.update_session(session["id"], answers=answers)
            reply = self._advance({**session, "answers": answers}, current["next"])
        else:
            language = session_language(session)
            message = (
                speak(script["fail_say"], language, session_persona(session))
                if script.get("fail_say")
                else FAIL_MESSAGES["ar" if language.lower().startswith("ar") else "en"]
            )
            turns.append({"role": "agent", "text": message})
            self.store.update_session(
                session["id"], status="abandoned", current_step=None, turns=turns
            )
            log.info("voice session %s abandoned at %s", session["id"], step)
            reply = _reply(script, [{"say": message, "key": "__fail__"}, {"hangup": True}], language,
                           session_persona(session))

        self.store.save_reply(call_sid, cache_step, attempt, reply)
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
                        action=self.gather_url(g["step"], g["attempt"], g.get("turn")),
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
        persona = session_persona(session)
        turns = list(session["turns"])
        verbs: list[dict[str, Any]] = []
        while key is not None:
            step = _step(script, key)
            if step["gather"]:
                next_turn = (session.get("turn") or 0) + 1
                self.store.update_session(session["id"], current_step=key, attempt=1, turn=next_turn)
                verbs.append(
                    self._gather_verb({**session, "turns": turns, "attempt": 1, "turn": next_turn}, step)
                )
                return _reply(script, verbs, language, persona)
            text = speak(step["say"], language, persona)
            turns.append({"role": "agent", "text": text})
            verbs.append({"say": text, "key": step["key"]})
            key = step["next"]

        commit = render_commit(
            script.get("commit") or {"records": []},
            answers=session["answers"],
            transcript=transcript_text(turns),
            call={
                "agent": speak("{{agent}}", crm_language(languages_of(script)), persona) if persona else "",
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
        return _reply(script, verbs, language, persona)

    def _gather_verb(self, session: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        """The gather prompt is a turn too; it is recorded with any says before it."""
        script = session["definition"]
        prompt = speak(step["say"], session_language(session), session_persona(session))
        turns = list(session["turns"]) + [{"role": "agent", "text": prompt}]
        self.store.update_session(session["id"], turns=turns)
        return {
            "gather": {
                "step": step["key"],
                "attempt": session["attempt"],
                "turn": session.get("turn"),
                "beep": bool(script.get("beep", True)),
                "prompt": prompt,
                "timeout": step["timeout"],
                "speech_timeout": step["speech_timeout"],
            }
        }


Reply = dict[str, Any]


def _reply(
    script: Mapping[str, Any] | None,
    verbs: list[dict[str, Any]],
    language: str | None = None,
    persona: Mapping[str, Any] | None = None,
) -> Reply:
    script = script or {}
    language = language or script.get("language")
    voices = (persona or {}).get("voices") or script.get("voices") or {}
    return {
        "script_id": script.get("id"),
        "language": language,
        "persona": (persona or {}).get("id"),
        "voice": script.get("voice"),
        "local_voice": voices.get(language) or script.get("local_voice"),
        "verbs": verbs,
    }


def session_persona(session: Mapping[str, Any]) -> dict[str, Any] | None:
    script = session.get("definition") or {}
    if not script.get("personas"):
        return None
    return find_persona(script, session.get("persona"))


def hold_text(script: Mapping[str, Any], language: str) -> str:
    """May contain {{agent}}; `speak` fills it with the caller's persona."""
    if script.get("hold_say"):
        return text_for(script["hold_say"], language)
    lang = "ar" if language.lower().startswith("ar") else "en"
    company = ((script.get("variables") or {}).get("company") or {}).get(language)
    opening = HOLD_OPENINGS[lang][(bool(script.get("personas")), bool(company))]
    return opening.replace("{company}", company or "") + " " + HOLD_MESSAGES[lang]


def languages_of(script: Mapping[str, Any]) -> list[str]:
    return list(script.get("languages") or [script.get("language") or "en-US"])


def session_language(session: Mapping[str, Any]) -> str:
    return session.get("language") or session["definition"].get("language") or "en-US"


def _step(script: Mapping[str, Any], key: str) -> dict[str, Any]:
    for step in script["steps"]:
        if step["key"] == key:
            return step
    raise KeyError(key)
