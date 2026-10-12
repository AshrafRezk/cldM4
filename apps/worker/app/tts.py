"""Text-to-speech providers for the SIM phone agent (Phase G).

Default is Microsoft neural voices via ``edge-tts`` (ar-EG Salma/Shakir, en-US,
fr-FR) with zero extra bill and no Metal use. Azure Speech is the supported-SLA
swap-in when ``TTS_PROVIDER=azure``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from typing import Any, Protocol

from .errors import CloudiatorError

log = logging.getLogger("cloudiator.tts")

# Spoken languages the voice agent advertises.
SUPPORTED_LANGUAGES = ("en", "ar-EG", "fr")

DEFAULT_VOICES = {
    "en": "en-US-JennyNeural",
    "ar-EG": "ar-EG-SalmaNeural",
    "fr": "fr-FR-DeniseNeural",
}

MALE_VOICES = {
    "en": "en-US-GuyNeural",
    "ar-EG": "ar-EG-ShakirNeural",
    "fr": "fr-FR-HenriNeural",
}

PCM_RATE = 16000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2


class TtsProvider(Protocol):
    async def synthesize(
        self, text: str, *, language: str, voice: str | None = None
    ) -> bytes:
        """Return 16-bit mono PCM at 16 kHz."""
        ...


def normalize_language(value: str | None) -> str:
    if not value:
        return "en"
    raw = value.strip().replace("_", "-")
    lowered = raw.lower()
    if lowered in ("en", "en-us", "en-gb", "english"):
        return "en"
    if lowered in ("fr", "fr-fr", "french"):
        return "fr"
    if lowered in ("ar", "ar-eg", "arz", "egyptian", "egyptian-arabic"):
        return "ar-EG"
    if lowered.startswith("ar"):
        return "ar-EG"
    if lowered.startswith("en"):
        return "en"
    if lowered.startswith("fr"):
        return "fr"
    raise CloudiatorError(
        400,
        "invalid_request_error",
        f"language must be one of {SUPPORTED_LANGUAGES}.",
        param="language",
    )


def resolve_voice(language: str, voice: str | None = None) -> str:
    lang = normalize_language(language)
    if voice:
        return voice.strip()
    return DEFAULT_VOICES[lang]


def wav_to_pcm16(data: bytes) -> bytes:
    """Extract PCM from a WAV container, resampling is not performed."""
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if channels != PCM_CHANNELS or width != PCM_SAMPLE_WIDTH:
        raise CloudiatorError(
            500,
            "internal_error",
            f"TTS returned unexpected WAV format ({channels}ch/{width}B).",
            error_type="server_error",
        )
    if rate != PCM_RATE:
        frames = _downsample_pcm16(frames, rate, PCM_RATE)
    return frames


def pcm16_to_wav(pcm: bytes, *, rate: int = PCM_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(PCM_CHANNELS)
        wf.setsampwidth(PCM_SAMPLE_WIDTH)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _downsample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    if src_rate == dst_rate:
        return pcm
    if src_rate % dst_rate != 0:
        # Naive drop for non-integer ratios is wrong; edge-tts is usually 24k.
        # Average adjacent samples for 24k→16k-ish by linear resample.
        import array

        samples = array.array("h")
        samples.frombytes(pcm)
        out = array.array("h")
        ratio = src_rate / dst_rate
        length = int(len(samples) / ratio)
        for i in range(length):
            src_index = i * ratio
            left = int(src_index)
            right = min(left + 1, len(samples) - 1)
            frac = src_index - left
            value = int(samples[left] * (1 - frac) + samples[right] * frac)
            out.append(max(-32768, min(32767, value)))
        return out.tobytes()
    factor = src_rate // dst_rate
    import array

    samples = array.array("h")
    samples.frombytes(pcm)
    out = array.array("h", samples[::factor])
    return out.tobytes()


class EdgeTtsProvider:
    """Microsoft neural voices through the edge-tts client (no Azure key)."""

    async def synthesize(
        self, text: str, *, language: str, voice: str | None = None
    ) -> bytes:
        cleaned = (text or "").strip()
        if not cleaned:
            raise CloudiatorError(400, "invalid_request_error", "text is required.", param="text")
        voice_id = resolve_voice(language, voice)
        try:
            import edge_tts  # type: ignore
        except ImportError as exc:
            raise CloudiatorError(
                503,
                "not_supported",
                "edge-tts is not installed. pip/uv add edge-tts in the worker venv.",
                error_type="server_error",
            ) from exc

        communicate = edge_tts.Communicate(cleaned, voice_id)
        mp3 = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3.extend(chunk["data"])
        if not mp3:
            raise CloudiatorError(
                500, "internal_error", "edge-tts returned no audio.", error_type="server_error"
            )
        return await asyncio.to_thread(_mp3_to_pcm16, bytes(mp3))


class AzureSpeechProvider:
    """Azure Cognitive Services Speech REST (SSML → WAV/PCM)."""

    def __init__(self, key: str, region: str) -> None:
        self.key = key
        self.region = region

    async def synthesize(
        self, text: str, *, language: str, voice: str | None = None
    ) -> bytes:
        cleaned = (text or "").strip()
        if not cleaned:
            raise CloudiatorError(400, "invalid_request_error", "text is required.", param="text")
        if not self.key or not self.region:
            raise CloudiatorError(
                503,
                "not_supported",
                "AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are required when TTS_PROVIDER=azure.",
                error_type="server_error",
            )
        voice_id = resolve_voice(language, voice)
        lang = normalize_language(language)
        xml_lang = {"en": "en-US", "ar-EG": "ar-EG", "fr": "fr-FR"}[lang]
        # Escape XML specials in spoken text.
        safe = (
            cleaned.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        ssml = (
            f"<speak version='1.0' xml:lang='{xml_lang}'>"
            f"<voice name='{voice_id}'>{safe}</voice></speak>"
        )
        import httpx

        url = f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",
            "User-Agent": "Cloudiator/1.0",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, content=ssml.encode("utf-8"), headers=headers)
        if response.status_code >= 400:
            raise CloudiatorError(
                502,
                "internal_error",
                f"Azure Speech failed ({response.status_code}).",
                error_type="server_error",
            )
        return wav_to_pcm16(response.content)


class FakeTtsProvider:
    """Deterministic silent/beep PCM for unit tests."""

    def __init__(self, pcm: bytes | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.pcm = pcm if pcm is not None else b"\x00\x00" * 1600  # 100ms silence

    async def synthesize(
        self, text: str, *, language: str, voice: str | None = None
    ) -> bytes:
        self.calls.append({"text": text, "language": language, "voice": voice})
        if not (text or "").strip():
            raise CloudiatorError(400, "invalid_request_error", "text is required.", param="text")
        return self.pcm


def build_tts_provider(settings) -> TtsProvider:
    provider = (getattr(settings, "tts_provider", None) or "edge").strip().lower()
    if provider == "fake":
        return FakeTtsProvider()
    if provider == "azure":
        return AzureSpeechProvider(
            key=getattr(settings, "azure_speech_key", None) or "",
            region=getattr(settings, "azure_speech_region", None) or "",
        )
    if provider in ("edge", "edge-tts"):
        return EdgeTtsProvider()
    raise CloudiatorError(
        500,
        "internal_error",
        f"Unknown TTS_PROVIDER {provider!r}. Use edge or azure.",
        error_type="server_error",
    )


def _mp3_to_pcm16(mp3: bytes) -> bytes:
    """Decode MP3 to 16 kHz mono PCM using stdlib + optional pydub/ffmpeg."""
    try:
        from pydub import AudioSegment  # type: ignore
    except ImportError:
        # Minimal fallback: shell out to ffmpeg if present.
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        if not shutil.which("ffmpeg"):
            raise CloudiatorError(
                503,
                "not_supported",
                "pydub or ffmpeg is required to decode edge-tts MP3 audio.",
                error_type="server_error",
            )
        with tempfile.TemporaryDirectory(prefix="tts-") as work:
            src = Path(work) / "in.mp3"
            dst = Path(work) / "out.wav"
            src.write_bytes(mp3)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(src),
                    "-ac",
                    "1",
                    "-ar",
                    str(PCM_RATE),
                    "-f",
                    "wav",
                    str(dst),
                ],
                check=True,
                capture_output=True,
            )
            return wav_to_pcm16(dst.read_bytes())

    segment = AudioSegment.from_file(io.BytesIO(mp3), format="mp3")
    segment = segment.set_channels(PCM_CHANNELS).set_frame_rate(PCM_RATE).set_sample_width(
        PCM_SAMPLE_WIDTH
    )
    return segment.raw_data


__all__ = [
    "DEFAULT_VOICES",
    "MALE_VOICES",
    "PCM_RATE",
    "SUPPORTED_LANGUAGES",
    "AzureSpeechProvider",
    "EdgeTtsProvider",
    "FakeTtsProvider",
    "TtsProvider",
    "build_tts_provider",
    "normalize_language",
    "pcm16_to_wav",
    "resolve_voice",
    "wav_to_pcm16",
]
