#!/usr/bin/env bash
# Phase A host setup. Run on the Mac Mini M4 (Darwin arm64) only.
set -euo pipefail

abort() {
  echo "abort: $*" >&2
  exit 1
}

echo "== Cloudiator mac-setup (Phase A) =="

UNAME_S="$(uname -s)"
UNAME_M="$(uname -m)"
[[ "$UNAME_S" == "Darwin" ]] || abort "this script is for macOS Darwin, not $UNAME_S"
[[ "$UNAME_M" == "arm64" ]] || abort "uname -m is $UNAME_M; need arm64 (Rosetta Terminal is not allowed)"

if command -v python3.11 >/dev/null 2>&1; then
  PY_MACHINE="$(python3.11 -c 'import platform; print(platform.machine())')"
  [[ "$PY_MACHINE" == "arm64" ]] || abort "python3.11 is $PY_MACHINE, not arm64"
  file "$(which python3.11)" | grep -qi arm64 || abort "python3.11 binary is not arm64"
else
  echo "python3.11 not on PATH yet; brew will install python@3.11"
fi

if brew list ollama >/dev/null 2>&1; then
  echo "Homebrew ollama is installed; uninstalling so Ollama.app owns 11434"
  brew uninstall ollama
fi
if brew list --cask ollama >/dev/null 2>&1; then
  brew uninstall --cask ollama
fi

command -v brew >/dev/null 2>&1 || abort "Homebrew missing. In Terminal:
  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
  echo 'eval \"\$(/opt/homebrew/bin/brew shellenv)\"' >> ~/.zprofile
  eval \"\$(/opt/homebrew/bin/brew shellenv)\"
then re-run this script from ~/cldM4."

eval "$(/opt/homebrew/bin/brew shellenv)"
brew install python@3.11 uv node@22 ffmpeg graphviz zbar poppler cloudflared git

export PATH="/opt/homebrew/opt/python@3.11/bin:/opt/homebrew/opt/node@22/bin:$PATH"
python3.11 -c "import platform; m=platform.machine(); assert m=='arm64', m"

if ! command -v ollama >/dev/null 2>&1; then
  abort "ollama CLI not found. Install the official .app from https://ollama.com/download/mac (not brew), open it once, then re-run."
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
uv python pin 3.11
uv python install 3.11

DATA="${CLOUDIATOR_DATA:-$HOME/Cloudiator}"
mkdir -p "$DATA"/{artifacts,logs,models}

# Time Machine / Spotlight exclusions (PLAN.md §4)
if command -v tmutil >/dev/null 2>&1; then
  tmutil addexclusion "$HOME/.ollama" || true
  tmutil addexclusion "$HOME/.cache/huggingface" || true
  tmutil addexclusion "$DATA/artifacts" || true
  tmutil addexclusion "$DATA/models" || true
  tmutil addexclusion "$DATA/logs" || true
fi
mkdir -p "$HOME/.ollama"
touch "$HOME/.ollama/.metadata_never_index"
touch "$DATA/artifacts/.metadata_never_index"
touch "$DATA/models/.metadata_never_index"
touch "$DATA/logs/.metadata_never_index"

# newsyslog rotation (needs sudo once)
NEWSYSLOG_SRC="$ROOT/infra/newsyslog.d/cloudiator.conf"
NEWSYSLOG_RENDERED="/tmp/cloudiator-newsyslog.conf"
sed -e "s|__HOME__|$HOME|g" -e "s|__USER__|$USER|g" "$NEWSYSLOG_SRC" > "$NEWSYSLOG_RENDERED"
echo "Installing log rotation (sudo) from $NEWSYSLOG_RENDERED"
sudo cp "$NEWSYSLOG_RENDERED" /etc/newsyslog.d/cloudiator.conf
sudo newsyslog -nvv || true

# Worker venv
cd "$ROOT/apps/worker"
uv sync --extra dev
# Apple Vision: Phase D uses this; smoke it now so Rosetta is caught early.
uv pip install pyobjc-framework-Vision ocrmac || abort "pyobjc Vision install failed"
if ! uv run python -c "import Vision"; then
  echo "Vision import failed; rebuilding venv against Homebrew framework Python"
  uv venv --python /opt/homebrew/opt/python@3.11/bin/python3.11
  uv sync --extra dev
  uv pip install pyobjc-framework-Vision ocrmac
  uv run python -c "import Vision" || abort "Vision still failed after framework Python rebuild"
fi

DEFAULT_MODEL="${DEFAULT_MODEL:-qwen3.5:9b}"
echo "Pulling DEFAULT_MODEL=$DEFAULT_MODEL and nomic-embed-text only (no 20B/27B/70B/120B)"
case "$DEFAULT_MODEL" in
  *70b*|*120b*|*27b*|*gpt-oss:20b*) abort "refusing to pull $DEFAULT_MODEL in Phase A" ;;
esac
ollama pull "$DEFAULT_MODEL"
ollama show "$DEFAULT_MODEL"
ollama pull nomic-embed-text
if [[ "${PULL_FALLBACK_3B:-}" == "1" ]]; then
  ollama pull llama3.2:3b
fi

ENV_FILE="$DATA/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  sed -e "s|/Users/REPLACE|$HOME|g" "$ROOT/.env.example" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Wrote $ENV_FILE from .env.example — edit DEFAULT_MODEL, secrets, PUBLIC_BASE_URL."
else
  echo "Keeping existing $ENV_FILE"
fi

grep -q '^OLLAMA_MAX_LOADED_MODELS=2' "$ENV_FILE" || echo "OLLAMA_MAX_LOADED_MODELS=2" >> "$ENV_FILE"
grep -q '^WEB_CONCURRENCY=1' "$ENV_FILE" || echo "WEB_CONCURRENCY=1" >> "$ENV_FILE"

"$ROOT/scripts/install-launchagents.sh"

echo
echo "Phase A software install finished."
echo "Next: run scripts/smoke-phase-a.sh, then fill docs/operator-checklist.md §8–9 from ollama show / timings."
echo "Ollama env (set on the Ollama.app / its LaunchAgent, not only the worker):"
cat "$ROOT/infra/launchagents/ollama.env"
