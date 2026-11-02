"""Speech-to-text helper for Egyptian Arabic mixed with English (and the odd
French word). Runs in ~/Cloudiator/tts-venv, not in the worker, and stays up so
the model loads once:

    python -I egy_stt_server.py MODEL_DIR THREADS

Reads one JSON request per line on stdin, {"id", "wav"} (16 kHz mono WAV),
and answers one JSON line on stdout, {"id", "text"} or {"id", "error"}.
Prints {"ready": true} once loaded. CPU only: the Metal GPU belongs to Gemma.

Model: IbrahimAmin/code-switched-egyptian-arabic-whisper-small (Apache-2.0),
Whisper Small fine-tuned on Egyptian Arabic-English code-switched speech. On
real calls it kept "a new case" and "I don't get your question" where
large-v3-turbo translated or garbled them. It can loop on near-silence
("طيب طيب طيب…"), so output length scales with the audio and 3-word repeats
are blocked.
"""

from __future__ import annotations

import json
import sys
import wave


def main() -> int:
    model_dir = sys.argv[1]
    threads = int(sys.argv[2]) if len(sys.argv) > 2 else 6

    import numpy as np
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    torch.set_num_threads(threads)
    processor = WhisperProcessor.from_pretrained(model_dir)
    model = WhisperForConditionalGeneration.from_pretrained(model_dir).eval()
    print(json.dumps({"ready": True}), flush=True)

    for raw in sys.stdin:
        try:
            request = json.loads(raw)
        except ValueError:
            continue
        rid = request.get("id")
        try:
            with wave.open(request["wav"], "rb") as w:
                frames = w.readframes(w.getnframes())
                rate = w.getframerate()
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            seconds = len(audio) / max(rate, 1)
            features = processor(audio, sampling_rate=16000, return_tensors="pt").input_features
            with torch.no_grad():
                ids = model.generate(
                    features,
                    task="transcribe",
                    language="ar",
                    num_beams=5,
                    # ~4 tokens a second of speech is generous; a silence loop
                    # cannot run past it.
                    max_new_tokens=int(min(160, 12 + seconds * 8)),
                    no_repeat_ngram_size=3,
                )
            text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
            print(json.dumps({"id": rid, "text": text}, ensure_ascii=False), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"id": rid, "error": f"{type(exc).__name__}: {exc}"[:300]}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
