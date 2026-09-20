#!/bin/zsh
# Template. scripts/install-launchagents.sh renders this to
# ~/Cloudiator/run-worker.sh with __HOME__ and __REPO__ substituted.
#
# The wrapper exists so ~/Cloudiator/.env stays the single source of truth for
# configuration instead of being duplicated into the plist.
#
# Do not `source` the env file. zsh treats unquoted parentheses as a parse
# error, and `set -e` would then exit before uvicorn starts — KeepAlive just
# crash-loops the LaunchAgent. scripts/lib/load-env.sh is a KEY=VALUE parser.
set -e

ENV_FILE="__HOME__/Cloudiator/.env"
# shellcheck disable=SC1091
. "__REPO__/scripts/lib/load-env.sh"
if [ ! -f "$ENV_FILE" ]; then
  printf 'missing %s\n' "$ENV_FILE" >&2
  exit 1
fi
load_env_file "$ENV_FILE"

export MPLBACKEND=Agg
# The worker asserts this is 2 and refuses to boot otherwise (PLAN.md §4).
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
export WEB_CONCURRENCY=1

cd __REPO__/apps/worker
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
