"""Subprocess entry for mlx-whisper. Never import mlx in the FastAPI process.

PLAN.md §9: TensorFlow/PyTorch/MLX stay out of the worker process. The parent
invokes ``python -m app.whisper_cli`` under the exclusive Metal slot, same
contract as mflux.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisper_cli")
    parser.add_argument("--audio", required=True, help="Path to an audio file Whisper can read")
    parser.add_argument(
        "--model",
        required=True,
        help="Local mlx-whisper model directory (never a network id in production)",
    )
    parser.add_argument("--language", default=None, help="Optional language hint (en, ar, fr, …)")
    parser.add_argument("--out", required=True, help="Write JSON transcript here")
    args = parser.parse_args(argv)

    audio = Path(args.audio)
    model = Path(args.model)
    if not audio.is_file():
        print(f"audio not found: {audio}", file=sys.stderr)
        return 2
    if not model.is_dir():
        print(f"model directory not found: {model}", file=sys.stderr)
        return 2

    try:
        import mlx_whisper  # type: ignore
    except ImportError as exc:
        print(f"mlx-whisper is not installed: {exc}", file=sys.stderr)
        return 3

    kwargs: dict = {"path_or_hf_repo": str(model)}
    if args.language:
        kwargs["language"] = args.language

    result = mlx_whisper.transcribe(str(audio), **kwargs)
    text = (result.get("text") if isinstance(result, dict) else None) or ""
    language = None
    if isinstance(result, dict):
        language = result.get("language")
    payload = {
        "text": text.strip(),
        "language": language or args.language,
        "model": str(model),
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
