"""The Egyptian code-switching speech model: a resident helper with a fallback."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from app import main
from app.voice import speech

FAKE_HELPER = """
import json, sys
print(json.dumps({"ready": True}), flush=True)
for raw in sys.stdin:
    req = json.loads(raw)
    print(json.dumps({"id": req["id"], "text": "لأ لأ a new case"}, ensure_ascii=False), flush=True)
"""

DEAD_HELPER = "import sys; sys.exit(3)"


def helper(tmp_path: Path, source: str) -> list[str]:
    script = tmp_path / "helper.py"
    script.write_text(source)
    return [sys.executable, str(script)]


def test_engine_choice(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    py = tmp_path / "python"
    py.write_text("")
    s = dataclasses.replace(main.settings, voice_stt_engine="auto", egyptian_stt_model=str(model), voicetut_python=str(py))
    assert speech.stt_engine(s) == "egyptian"
    assert speech.stt_engine(dataclasses.replace(s, egyptian_stt_model=str(tmp_path / "missing"))) == "whisper_cpp"
    assert speech.stt_engine(dataclasses.replace(s, voice_stt_engine="whisper_cpp")) == "whisper_cpp"


async def test_the_helper_answers_and_restarts_after_a_crash(tmp_path):
    client = speech.EgyptianSTT(helper(tmp_path, FAKE_HELPER), load_timeout=10, timeout=10)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    assert await client.transcribe(wav) == "لأ لأ a new case"
    client.proc.kill()
    await client.proc.wait()
    assert await client.transcribe(wav) == "لأ لأ a new case", "a dead helper is started again"
    await client.close()


async def test_a_helper_that_never_starts_is_unavailable(tmp_path):
    client = speech.EgyptianSTT(helper(tmp_path, DEAD_HELPER), load_timeout=5, timeout=5)
    with pytest.raises(speech.SpeechUnavailable):
        await client.transcribe(tmp_path / "a.wav")


@pytest.mark.skipif(not Path(main.settings.ffmpeg_bin).exists(), reason="needs ffmpeg")
async def test_transcribe_falls_back_to_whisper_cpp(tmp_path, monkeypatch):
    import subprocess

    wav = tmp_path / "in.wav"
    subprocess.run([main.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=300:duration=1", str(wav)], check=True)
    model = tmp_path / "model"
    model.mkdir()
    py = tmp_path / "python"
    py.write_text("")
    whisper_model = tmp_path / "ggml.bin"
    whisper_model.write_text("")
    s = dataclasses.replace(main.settings, voice_stt_engine="egyptian", egyptian_stt_model=str(model),
                            voicetut_python=str(py), whisper_cpp_bin=sys.executable, whisper_model=str(whisper_model))
    monkeypatch.setattr(speech, "_egyptian", speech.EgyptianSTT(helper(tmp_path, DEAD_HELPER), load_timeout=5))

    async def whisper_cpp(*args, **kwargs):
        return "صفر واحد اتنين تلاتة"

    monkeypatch.setattr(speech, "_whisper_cpp", whisper_cpp)
    assert await speech.transcribe(wav.read_bytes(), language="ar-EG", settings=s) == "0123"

    monkeypatch.setattr(speech, "_egyptian", speech.EgyptianSTT(helper(tmp_path, FAKE_HELPER), load_timeout=5))
    assert await speech.transcribe(wav.read_bytes(), language="ar-EG", settings=s) == "لأ لأ a new case"
    await speech._egyptian.close()


@pytest.mark.parametrize("heard, expected", [
    ("صفر 1 صفر 1 إثنان ثلاثة أربعة خمسة ستة سبعة ثمانية.", "01012345678"),
    ("رقمي زيرو واحد اتنين اتنين", "رقمي 0122"),
    ("zero one two three", "0123"),
    ("deux trois quatre", "234"),
    ("واحد بس", "واحد بس"),
    ("عندي واحد سؤال", "عندي واحد سؤال"),
])
def test_spoken_number_words_become_digits_only_in_runs(heard, expected):
    assert speech.normalize_digits(speech.number_words_to_digits(heard)) == expected


@pytest.mark.skipif(not Path(main.settings.ffmpeg_bin).exists(), reason="needs ffmpeg")
@pytest.mark.parametrize("volume, seconds, is_speech", [(0.3, 1.0, True), (0.008, 2.0, False), (0.3, 0.15, False), (1.0, 30, True)])
def test_near_silence_is_never_transcribed(tmp_path, volume, seconds, is_speech):
    """Both models invent fluent text from near-silence ("ماشي طيب"); no real speech, no transcript."""
    import subprocess

    wav = tmp_path / "x.wav"
    subprocess.run([main.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
                    "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1",
                    "-filter_complex", f"[0]volume={volume}[a];[a][1]concat=n=2:v=0:a=1",
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
    assert (speech.speech_seconds(wav) >= speech.MIN_SPEECH_SECONDS) is is_speech
