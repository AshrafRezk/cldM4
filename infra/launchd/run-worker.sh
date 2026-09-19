#!/bin/zsh
# Template. scripts/install-launchagents.sh renders this to
# ~/Cloudiator/run-worker.sh with __HOME__ and __REPO__ substituted.
#
# The wrapper exists so ~/Cloudiator/.env stays the single source of truth for
# configuration instead of being duplicated into the plist.
set -e

set -a
source __HOME__/Cloudiator/.env
set +a

export MPLBACKEND=Agg
# The worker asserts this is 2 and refuses to boot otherwise (PLAN.md §4).
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
export WEB_CONCURRENCY=1

cd __REPO__/apps/worker
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
