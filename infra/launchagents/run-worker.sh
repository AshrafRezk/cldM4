#!/bin/zsh
# Installed to ~/Cloudiator/run-worker.sh by scripts/install-launchagents.sh
set -euo pipefail
set -a
source __DATA__/.env
set +a
export MPLBACKEND=Agg
export WEB_CONCURRENCY=1
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
cd __REPO__/apps/worker
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
