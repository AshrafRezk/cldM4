"""Re-hear a finished call's answers with the slower, more accurate model.
Runs in ~/Cloudiator/tts-venv, not in the worker, once per call:

    python -I egy_refine.py MODEL_DIR THREADS JOBS.json

JOBS.json: [{"id", "wav"}] (16 kHz mono WAV). Prints one JSON line per job,
{"id", "text"} or {"id", "error"}. CPU only: the Metal GPU belongs to Gemma.

Model: Whisper large-v2 fine-tuned on Arabic-English code-switching
(MohamedRashad/Arabic-Whisper-CodeSwitching-Edition, GPL-3.0), as the
CTranslate2 build Mano200600/faster-whisper-large-v2-ar-codeswitching. On the
saved test calls it got names ("أشرف رزق") and an 11-digit mobile right where
the live model did not, at ~6 s an answer: too slow to talk with, fine after.

The build ships no tokenizer.json; faster-whisper then uses openai/whisper-tiny's
(the same multilingual vocabulary), which must be in the Hugging Face cache:
the worker runs this with HF_HUB_OFFLINE=1.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    model_dir, threads, jobs_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    from faster_whisper import WhisperModel

    model = WhisperModel(model_dir, device="cpu", compute_type="int8", cpu_threads=threads)
    for job in json.load(open(jobs_path, encoding="utf-8")):
        try:
            segments, _info = model.transcribe(
                job["wav"], language="ar", task="transcribe", beam_size=5,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            print(json.dumps({"id": job["id"], "text": text}, ensure_ascii=False), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"id": job["id"], "error": f"{type(exc).__name__}: {exc}"[:300]}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
