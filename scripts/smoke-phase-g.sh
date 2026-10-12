#!/usr/bin/env bash
# Phase G smoke: scopes, TTS, voice line CRUD, busy-without-handset.
# Whisper exclusive + live SIM call are proven on the Mini with a handset.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/worker"

if [[ ! -x .venv/bin/pytest ]]; then
  echo "missing apps/worker/.venv — run: cd apps/worker && uv sync --extra dev" >&2
  exit 1
fi

.venv/bin/pytest -q \
  tests/test_whisper_transcriptions.py \
  tests/test_tts.py \
  tests/test_voice_agent.py

echo "phase G unit smoke green"
echo "On the Mini: download WHISPER_MODEL_PATH, connect apps/phone-bridge, then place two sequential SIM calls."
