"""Local speech for the browser call. No vendor, no Metal.

TTS is macOS `say` (Majed for Arabic, Samantha for English), cached on disk
by text+voice: script prompts are static, so after the first call every prompt
is a file read.

STT is whisper.cpp on the **CPU** (`--no-gpu`). The GPU belongs to Gemma
(PLAN.md: one Metal model at a time); a CPU transcription of a short answer
never unloads chat. One transcription at a time: a second caller waits a
second rather than both being slow. Apple's recognizer is not used because it
only does English on-device; Arabic goes to Apple's servers.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

log = logging.getLogger("cloudiator.voice.speech")

DEFAULT_VOICES = {"ar": "Majed", "en": "Samantha"}
SAY = "/usr/bin/say"
TTS_TIMEOUT = 30.0
STT_TIMEOUT = 45.0
MAX_UTTERANCE_SECONDS = 30

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "0123456789" * 2)
DIGIT_GAP = re.compile(r"(?<=\d)[ \-\u2010-\u2015]+(?=\d)")
NOISE_TAGS = re.compile(r"\[[^\]]*\]|\([^)]*\)")

_stt_lock = asyncio.Semaphore(1)


class SpeechUnavailable(Exception):
    """The configured speech backend cannot run on this machine."""


def _lang(language: str | None) -> str:
    return (language or "en").split("-")[0].split("_")[0].lower()


def voice_for(language: str | None, local_voice: str | None) -> str | None:
    return local_voice or DEFAULT_VOICES.get(_lang(language))


async def _run(args: list[str], timeout: float) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SpeechUnavailable(f"{Path(args[0]).name} timed out after {timeout:.0f}s")
    if proc.returncode != 0:
        raise SpeechUnavailable(
            f"{Path(args[0]).name} exited {proc.returncode}: {err.decode(errors='replace')[-300:]}"
        )
    return out


async def synthesize(text: str, *, language: str | None, local_voice: str | None, cache_dir: str) -> bytes:
    """AAC in an .m4a container; every current browser plays it."""
    voice = voice_for(language, local_voice)
    key = hashlib.sha256(f"{voice}\0{text}".encode()).hexdigest()[:32]
    cache = Path(os.path.expanduser(cache_dir))
    path = cache / f"{key}.m4a"
    if path.is_file():
        return path.read_bytes()
    if not os.path.exists(SAY):
        raise SpeechUnavailable("macOS `say` is not available")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "text.txt"
        text_file.write_text(text, encoding="utf-8")
        out = Path(tmp) / "out.m4a"
        args = [SAY, "--file-format=m4af", "--data-format=aac", "-o", str(out), "-f", str(text_file)]
        if voice:
            args[1:1] = ["-v", voice]
        await _run(args, TTS_TIMEOUT)
        data = out.read_bytes()
    path.write_bytes(data)
    return data


async def synthesize_data_url(text: str, **kwargs) -> str:
    return "data:audio/mp4;base64," + base64.b64encode(await synthesize(text, **kwargs)).decode()


def audio_ctx(seconds: float) -> int:
    """Encoder window for a clip, in whisper frames (1500 = 30 s).

    The encoder always runs its whole window, so a 2 s answer at the default
    1500 costs as much as 30 s of speech (~7 s on the M4 CPU). Measured on the
    Mini with large-v3-turbo q5_0, 8 threads: windows at ~1.5x the clip + 2 s
    keep Arabic names and digits exact; below 512 short answers repeat
    themselves ("أحمد علي أحمد علي"), so 512 (~10 s) is the floor.
    """
    frames = (seconds * 1.5 + 2) / 30 * 1500
    return int(min(1500, max(512, -(-frames // 64) * 64)))


def stt_engine(settings) -> str:
    """auto: the Egyptian code-switching model when installed, else whisper.cpp."""
    choice = (settings.voice_stt_engine or "auto").lower()
    egyptian_ready = os.path.isdir(settings.egyptian_stt_model) and os.path.exists(settings.voicetut_python)
    if choice in ("auto", "egyptian"):
        return "egyptian" if egyptian_ready else "whisper_cpp"
    return "whisper_cpp"


class EgyptianSTT:
    """The resident helper (egy_stt_server.py): one model load, then one JSON
    line per answer. Restarted if it dies; callers fall back to whisper.cpp."""

    def __init__(self, command: list[str], *, load_timeout: float = 120.0, timeout: float = STT_TIMEOUT) -> None:
        self.command = command
        self.load_timeout = load_timeout
        self.timeout = timeout
        self.proc: asyncio.subprocess.Process | None = None
        self._next = 0

    async def _ensure(self) -> asyncio.subprocess.Process:
        if self.proc is not None and self.proc.returncode is None:
            return self.proc
        self.proc = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        line = await asyncio.wait_for(self.proc.stdout.readline(), self.load_timeout)  # type: ignore[union-attr]
        if not line or not json.loads(line).get("ready"):
            await self.close()
            raise SpeechUnavailable("Egyptian speech model did not start")
        log.info("egyptian speech model loaded")
        return self.proc

    async def transcribe(self, wav: Path) -> str:
        try:
            proc = await self._ensure()
            self._next += 1
            rid = self._next
            proc.stdin.write((json.dumps({"id": rid, "wav": str(wav)}) + "\n").encode())  # type: ignore[union-attr]
            await proc.stdin.drain()  # type: ignore[union-attr]
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), self.timeout)  # type: ignore[union-attr]
                if not line:
                    raise SpeechUnavailable("Egyptian speech model exited")
                reply = json.loads(line)
                if reply.get("id") == rid:
                    break
        except (asyncio.TimeoutError, OSError, ValueError) as exc:
            await self.close()
            raise SpeechUnavailable(f"Egyptian speech model failed: {type(exc).__name__}") from exc
        except SpeechUnavailable:
            await self.close()
            raise
        if "error" in reply:
            raise SpeechUnavailable(reply["error"])
        return reply.get("text") or ""

    async def close(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None


_egyptian: EgyptianSTT | None = None


def egyptian_client(settings) -> EgyptianSTT:
    global _egyptian
    if _egyptian is None:
        script = Path(__file__).with_name("egy_stt_server.py")
        _egyptian = EgyptianSTT([
            "/usr/bin/nice", "-n", "5", settings.voicetut_python, "-I", str(script),
            settings.egyptian_stt_model, str(settings.egyptian_stt_threads),
        ])
    return _egyptian


async def transcribe(audio: bytes, *, language: str | None, settings) -> str:
    if not audio:
        return ""
    engine = stt_engine(settings)
    binary = settings.whisper_cpp_bin
    model = os.path.expanduser(settings.whisper_model)
    whisper_ready = bool(binary) and os.path.exists(binary) and os.path.isfile(model)
    if engine == "whisper_cpp" and not whisper_ready:
        raise SpeechUnavailable(f"no speech model: whisper.cpp ({binary}) or its model ({model}) is missing")
    async with _stt_lock:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "in"
            raw.write_bytes(audio)
            wav = Path(tmp) / "in.wav"
            # Whatever the browser sent (WAV from the call page, webm/mp4 from
            # elsewhere) becomes 16 kHz mono 16-bit PCM, capped in length.
            await _run(
                [settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-i", str(raw),
                 "-t", str(MAX_UTTERANCE_SECONDS), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                 "-f", "wav", str(wav)],
                20.0,
            )
            if speech_seconds(wav) < MIN_SPEECH_SECONDS:
                # Both models invent fluent text from near-silence ("ماشي طيب",
                # subtitle credits). No real speech, no transcript.
                return ""
            text = None
            if engine == "egyptian":
                try:
                    text = await egyptian_client(settings).transcribe(wav)
                except SpeechUnavailable as exc:
                    if not whisper_ready:
                        raise
                    log.warning("egyptian speech model unavailable, using whisper.cpp: %s", exc)
            if text is None:
                text = await _whisper_cpp(wav, language, settings, binary, model, Path(tmp))
    return clean_transcript(text)


def clean_transcript(text: str) -> str:
    """Every model's output goes through the same filters."""
    # whisper.cpp marks silence and noise as [BLANK_AUDIO], (music), etc.
    text = " ".join(NOISE_TAGS.sub(" ", text).split())
    return normalize_digits(number_words_to_digits(collapse_repeats(drop_hallucinations(text))))


MIN_SPEECH_SECONDS = 0.3
_FRAME = 480  # 30 ms at 16 kHz


def speech_seconds(wav: Path) -> float:
    """Seconds of audio clearly louder than both the room and an absolute floor.

    Measured on real calls: windows that peaked at RMS 0.012-0.015 held no
    words yet produced confident transcripts; answers spoken at 0.1-0.2 pass
    easily, and a quiet one at 0.026 still clears 0.01."""
    import array
    import math

    data = array.array("h")
    data.frombytes(wav.read_bytes()[44:])
    if sys.byteorder != "little":
        data.byteswap()
    frames = []
    for start in range(0, len(data) - _FRAME + 1, _FRAME):
        chunk = data[start:start + _FRAME]
        frames.append(math.sqrt(sum(x * x for x in chunk) / _FRAME) / 32768.0)
    if not frames:
        return 0.0
    noise = sorted(frames)[len(frames) // 10]  # the room between words
    # Capped so a caller who never pauses (no quiet frames to learn the room
    # from) still counts: real answers measured 0.1-0.2, far above 0.05.
    threshold = min(0.05, max(0.01, noise * 4))
    return sum(1 for rms in frames if rms > threshold) * _FRAME / 16000


async def _whisper_cpp(wav: Path, language: str | None, settings, binary: str, model: str, tmp: Path) -> str:
    base = tmp / "out"
    seconds = max(0, wav.stat().st_size - 44) / 32000  # 16 kHz, 16-bit mono
    await _run(
        [binary, "-m", model, "-f", str(wav), "-l", _lang(language),
         "--no-gpu", "-t", str(settings.whisper_threads), "-bs", "5",
         # No initial prompt: tested on real Egyptian/English calls, it
         # leaks its own words into transcripts ("مش عارف. مفهمتش.").
         "-ac", str(audio_ctx(seconds)), "-mc", "0", "-nt", "-np",
         "-otxt", "-of", str(base)],
        STT_TIMEOUT,
    )
    text_path = base.with_suffix(".txt")
    return text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""


# Spoken digits come back as words ("صفر 1 صفر 1 إثنان ثلاثة"), in whichever
# language the caller used for that stretch.
NUMBER_WORDS = {
    "صفر": "0", "زيرو": "0", "واحد": "1", "اتنين": "2", "اثنين": "2", "اثنان": "2", "إثنين": "2", "إثنان": "2",
    "تلاتة": "3", "تلاته": "3", "ثلاثة": "3", "ثلاثه": "3", "اربعة": "4", "أربعة": "4", "اربعه": "4", "أربعه": "4",
    "خمسة": "5", "خمسه": "5", "ستة": "6", "سته": "6", "سبعة": "7", "سبعه": "7", "تمانية": "8", "تمانيه": "8",
    "ثمانية": "8", "ثمانيه": "8", "تسعة": "9", "تسعه": "9",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "oh": "0",
    "zéro": "0", "un": "1", "deux": "2", "trois": "3", "quatre": "4", "cinq": "5", "sept": "7", "huit": "8", "neuf": "9",
}


def number_words_to_digits(text: str) -> str:
    """Only inside a run of two or more number tokens, so a phone number
    becomes digits but "واحد بس" (just one) keeps its words."""
    tokens = text.split()
    def as_digit(token: str) -> str | None:
        bare = token.strip(".,،!?؟").lower()
        if bare.isdigit():
            return bare
        bare = bare[1:] if bare.startswith("و") and bare[1:] in NUMBER_WORDS else bare  # "وتلاتة"
        return NUMBER_WORDS.get(bare)
    out, run = [], []
    for token in tokens + [None]:  # type: ignore[list-item]
        digit = as_digit(token) if token is not None else None
        if digit is not None:
            run.append((token, digit))
            continue
        if len(run) >= 2:
            out.append(" ".join(d for _t, d in run))
        else:
            out.extend(t for t, _d in run)
        run = []
        if token is not None:
            out.append(token)
    return " ".join(out)


# What whisper writes when it hears near-silence: subtitle credits and channel
# outros from its training data. Measured on real calls ("ترجمة نانسي قنقر",
# "اشتركوا في القناة"); a line made of these is silence, so the caller is asked again.
HALLUCINATIONS = [
    "ترجمة نانسي قنقر", "نانسي قنقر", "اشتركوا في القناة", "اشترك في القناة", "لا تنسوا الاشتراك",
    "شكرا للمشاهدة", "شكراً للمشاهدة", "شكرا على المشاهدة", "ترجمة", "موسيقى",
    "thanks for watching", "thank you for watching", "please subscribe", "subscribe to the channel",
    "subtitles by", "amara.org", "merci d'avoir regardé", "sous-titres",
]
_HALLUCINATION_PATTERNS = sorted(HALLUCINATIONS, key=len, reverse=True)


def drop_hallucinations(text: str) -> str:
    lowered = text.lower()
    for phrase in _HALLUCINATION_PATTERNS:
        lowered = lowered.replace(phrase, " ")
    if not re.sub(r"[\W_]+", "", lowered):
        return ""
    return text


def collapse_repeats(text: str) -> str:
    """"I don't get your question. I don't get your question." -> once."""
    words = text.split()
    changed = True
    while changed:
        changed = False
        for size in range(len(words) // 2, 0, -1):
            for start in range(0, len(words) - 2 * size + 1):
                a = [w.strip(".,،!?؟") for w in words[start:start + size]]
                b = [w.strip(".,،!?؟") for w in words[start + size:start + 2 * size]]
                if a == b and (size > 1 or len(a[0]) > 2):
                    del words[start + size:start + 2 * size]
                    changed = True
                    break
            if changed:
                break
    return " ".join(words)


def normalize_digits(text: str) -> str:
    """Spoken numbers come back grouped ("01-01-2-3-4", "٠١٠ ١٢٣"). A phone or
    account number is one token in a CRM field, so digits become 0-9 and the
    dashes/spaces between digits go. Decimal points and other text stay."""
    return DIGIT_GAP.sub("", text.translate(ARABIC_DIGITS))
