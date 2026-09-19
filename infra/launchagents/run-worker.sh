#!/bin/bash
# Installed to ~/Cloudiator/run-worker.sh by scripts/install-launchagents.sh
# Must be bash, not zsh: zsh NOMATCH treats '?' in DATABASE_URL as a glob and
# exits before uvicorn starts (KeepAlive crash loop, nothing on :8080).
set -euo pipefail

load_dotenv() {
  local file="$1" line key val
  [[ -f "$file" ]] || {
    echo "abort: missing env file $file" >&2
    exit 1
  }
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    # trim leading whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    case "$line" in
      ''|\#*) continue ;;
    esac
    line="${line#export }"
    key="${line%%=*}"
    val="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ ${#val} -ge 2 && "${val:0:1}" == '"' && "${val: -1}" == '"' ]]; then
      val="${val:1:${#val}-2}"
    elif [[ ${#val} -ge 2 && "${val:0:1}" == "'" && "${val: -1}" == "'" ]]; then
      val="${val:1:${#val}-2}"
    fi
    printf -v "$key" '%s' "$val"
    export "$key"
  done < "$file"
}

ENV_FILE="${CLOUDIATOR_ENV_FILE:-__DATA__/.env}"
load_dotenv "$ENV_FILE"

if [[ "${1:-}" == "--dump-keys" ]]; then
  printf '%s\n' "${DATABASE_URL-}" "${NOMINATIM_USER_AGENT-}" "${OLLAMA_MAX_LOADED_MODELS-}" "${WEB_CONCURRENCY-}"
  exit 0
fi

export MPLBACKEND=Agg
export WEB_CONCURRENCY=1
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
export CLOUDIATOR_ENV="${CLOUDIATOR_ENV:-production}"

REPO_WORKER="${CLOUDIATOR_WORKER_DIR:-__REPO__/apps/worker}"
cd "$REPO_WORKER"
UVICORN="$PWD/.venv/bin/uvicorn"
if [[ ! -x "$UVICORN" ]]; then
  echo "abort: missing $UVICORN — run scripts/mac-setup.sh" >&2
  exit 1
fi
echo "starting $UVICORN on 127.0.0.1:8080 workers=1" >&2
exec "$UVICORN" app.main:app --host 127.0.0.1 --port 8080 --workers 1
