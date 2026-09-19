#!/bin/bash
# Persist Ollama.app env into the Aqua session. Does not start or kill Ollama
# (killall + open -a races LaunchServices: LS error -600).
set -euo pipefail
launchctl setenv OLLAMA_HOST 127.0.0.1:11434
launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_MAX_QUEUE 32
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_KEEP_ALIVE 30m
launchctl setenv OLLAMA_ORIGINS http://127.0.0.1:8080
# If the app is not already serving, open the official .app (not brew).
if ! curl -sf --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  open /Applications/Ollama.app 2>/dev/null || true
fi
