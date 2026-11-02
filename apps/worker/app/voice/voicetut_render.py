"""Render script lines with VoiceTut-TTS. Runs in ~/Cloudiator/tts-venv, not
in the worker: `python -I voicetut_render.py jobs.json THREADS`.

jobs.json: [{"text", "language": "ar"|"en", "speaker", "wav"}]. Writes each
`wav` and prints `done <index>` on stdout right after it; a line that fails
is skipped and reported on stderr. CPU only: the Metal GPU belongs to Gemma.
"""

from __future__ import annotations

import json
import sys
import time


def main() -> int:
    jobs = json.load(open(sys.argv[1], encoding="utf-8"))
    threads = int(sys.argv[2]) if len(sys.argv) > 2 else 6

    import torch

    torch.set_num_threads(threads)
    from voicetut_tts import VoiceTutTTS

    started = time.time()
    tts = VoiceTutTTS.from_pretrained("mohammedaly22/VoiceTut-TTS", device="cpu", dtype="float32")
    print(f"loaded in {time.time() - started:.1f}s", file=sys.stderr, flush=True)

    failures = 0
    for index, job in enumerate(jobs):
        t = time.time()
        try:
            tts.synthesize(job["text"], speaker=job["speaker"], language=job["language"], output=job["wav"])
            print(f"ok {job['language']} {time.time() - t:.1f}s {job['text'][:40]}", file=sys.stderr, flush=True)
            # The worker publishes each clip as soon as it sees this, so callers
            # get natural audio line by line instead of after the whole batch.
            print(f"done {index}", flush=True)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"failed {job['language']} {job['speaker']}: {exc}", file=sys.stderr, flush=True)
    return 0 if failures < len(jobs) else 1


if __name__ == "__main__":
    sys.exit(main())
