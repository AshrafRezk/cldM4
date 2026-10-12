"""CPU voice-activity detection for call uplink (no GPU)."""

from __future__ import annotations

import array
import struct
from dataclasses import dataclass


def _rms_pcm16(frame: bytes) -> int:
    if not frame:
        return 0
    samples = array.array("h")
    samples.frombytes(frame)
    if not samples:
        return 0
    acc = 0
    for sample in samples:
        acc += sample * sample
    return int((acc / len(samples)) ** 0.5)


@dataclass
class VadConfig:
    sample_rate: int = 16000
    frame_ms: int = 30
    # RMS energy threshold for int16 PCM (tuned for phone levels).
    energy_threshold: int = 500
    # End of utterance after this many silent frames.
    silence_frames: int = 20  # ~600ms at 30ms
    # Minimum speech frames before we accept an utterance.
    min_speech_frames: int = 10  # ~300ms
    # Hard cap so a stuck open mic cannot grow forever (~30s).
    max_speech_frames: int = 1000


class EnergyVad:
    """Simple energy VAD. Good enough to gate Whisper; no model weights."""

    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig()
        self.frame_bytes = int(self.config.sample_rate * self.config.frame_ms / 1000) * 2
        self._buf = bytearray()
        self._speech = bytearray()
        self._in_speech = False
        self._silent = 0
        self._speech_frames = 0

    def reset(self) -> None:
        self._buf.clear()
        self._speech.clear()
        self._in_speech = False
        self._silent = 0
        self._speech_frames = 0

    def feed(self, pcm: bytes) -> list[bytes]:
        """Feed uplink PCM; return zero or more completed utterances."""
        if not pcm:
            return []
        self._buf.extend(pcm)
        utterances: list[bytes] = []
        while len(self._buf) >= self.frame_bytes:
            frame = bytes(self._buf[: self.frame_bytes])
            del self._buf[: self.frame_bytes]
            done = self._consume_frame(frame)
            if done is not None:
                utterances.append(done)
        return utterances

    def flush(self) -> bytes | None:
        if self._in_speech and self._speech_frames >= self.config.min_speech_frames:
            utterance = bytes(self._speech)
            self.reset()
            return utterance
        self.reset()
        return None

    def _consume_frame(self, frame: bytes) -> bytes | None:
        energy = _rms_pcm16(frame)
        voiced = energy >= self.config.energy_threshold
        if voiced:
            if not self._in_speech:
                self._in_speech = True
                self._speech.clear()
                self._speech_frames = 0
            self._speech.extend(frame)
            self._speech_frames += 1
            self._silent = 0
            if self._speech_frames >= self.config.max_speech_frames:
                utterance = bytes(self._speech)
                self._speech.clear()
                self._in_speech = False
                self._speech_frames = 0
                return utterance
            return None

        if self._in_speech:
            self._speech.extend(frame)
            self._silent += 1
            if self._silent >= self.config.silence_frames:
                if self._speech_frames >= self.config.min_speech_frames:
                    utterance = bytes(self._speech)
                else:
                    utterance = None
                self._speech.clear()
                self._in_speech = False
                self._speech_frames = 0
                self._silent = 0
                return utterance
        return None


def pcm_duration_ms(pcm: bytes, sample_rate: int = 16000) -> int:
    if not pcm:
        return 0
    samples = len(pcm) // 2
    return int(samples * 1000 / sample_rate)


def silence_pcm(ms: int = 100, sample_rate: int = 16000) -> bytes:
    n = int(sample_rate * ms / 1000)
    return struct.pack(f"<{n}h", *([0] * n))
