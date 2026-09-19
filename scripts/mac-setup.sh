#!/usr/bin/env bash
# Phase A host setup for the Mac Mini (docs/host-setup.md).
#
# Idempotent. Run it again after changing .env or upgrading Homebrew.
#
#   scripts/mac-setup.sh
#   scripts/mac-setup.sh --skip-brew --skip-pulls
#   scripts/mac-setup.sh --with-fallback-model    # also pull llama3.2:3b
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SKIP_BREW=0
SKIP_PULLS=0
WITH_FALLBACK=0
for arg in "$@"; do
  case "$arg" in
    --skip-brew)           SKIP_BREW=1 ;;
    --skip-pulls)          SKIP_PULLS=1 ;;
    --with-fallback-model) WITH_FALLBACK=1 ;;
    *) die "unknown option: $arg" ;;
  esac
done

# Gate first. Everything below installs wheels that are wrong under Rosetta.
require_arm64_macos

load_env_file "$HOME/Cloudiator/.env"
DEFAULT_MODEL="${DEFAULT_MODEL:-gemma4:e4b-it-qat}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
CLOUDIATOR_HOME="$HOME/Cloudiator"

printf '%sCloudiator host setup%s  (user: %s, repo: %s)\n' "$C_BOLD" "$C_OFF" "$(id -un)" "$ROOT"

# --------------------------------------------------------------------------
section "Homebrew packages (docs/host-setup.md §2)"

if [ "$SKIP_BREW" = "1" ]; then
  info "skipped"
elif ! command -v brew >/dev/null 2>&1; then
  fail "brew not on PATH. Install Homebrew, then: eval \"\$(/opt/homebrew/bin/brew shellenv)\""
else
  # Two Ollama installs fight over 11434, and if the brew service wins it runs
  # without the LaunchAgent env, so the whole 24 GB discipline stops applying.
  if brew list 2>/dev/null | grep -qi '^ollama$'; then
    info "removing brew ollama (only the official .app may own 11434)"
    brew uninstall ollama >/dev/null 2>&1 && pass "brew ollama removed" || fail "could not remove brew ollama"
  else
    pass "no brew ollama"
  fi

  for pkg in python@3.11 uv node@22 ffmpeg graphviz zbar poppler cloudflared git; do
    if brew list "$pkg" >/dev/null 2>&1; then
      pass "$pkg already installed"
    else
      info "installing $pkg"
      brew install "$pkg" >/dev/null 2>&1 && pass "$pkg installed" || fail "brew install $pkg failed"
    fi
  done
fi

if [ -d "/Applications/Ollama.app" ]; then
  pass "Ollama.app present"
else
  fail "Ollama.app missing. Install the official app: open https://ollama.com/download/mac"
fi

# --------------------------------------------------------------------------
section "Directories, Time Machine and Spotlight exclusions (docs/host-setup.md §3)"

mkdir -p "$CLOUDIATOR_HOME/artifacts" "$CLOUDIATOR_HOME/logs" "$CLOUDIATOR_HOME/models"
pass "created $CLOUDIATOR_HOME/{artifacts,logs,models}"

# Weight caches are tens of GB of rarely-changing files. Time Machine copies
# them on a schedule and mdworker indexes GGUFs, both mid-generation.
for path in "$HOME/.ollama" "$HOME/.cache/huggingface" "$CLOUDIATOR_HOME/artifacts" \
            "$CLOUDIATOR_HOME/models" "$CLOUDIATOR_HOME/logs"; do
  mkdir -p "$path"
  if tmutil addexclusion "$path" >/dev/null 2>&1; then
    pass "Time Machine excludes $path"
  else
    warn "could not exclude $path from Time Machine (add it by hand in System Settings)"
  fi
  touch "$path/.metadata_never_index" 2>/dev/null \
    && pass "Spotlight excludes $path" \
    || warn "could not write $path/.metadata_never_index"
done

# --------------------------------------------------------------------------
section "Log rotation (docs/host-setup.md §7)"

# KeepAlive=true plus an unrotated StandardOutPath is an unbounded file, and a
# full SSD takes down Ollama, the worker, and cloudflared simultaneously.
NEWSYSLOG_CONF="/etc/newsyslog.d/cloudiator.conf"
NEWSYSLOG_BODY="$(printf '# logfilename                               [owner:group]  mode count size(KB) when  flags\n%s/logs/worker.log   %s:staff  644  7     10240    *     GJ\n%s/logs/worker.err   %s:staff  644  7     10240    *     GJ\n' \
  "$CLOUDIATOR_HOME" "$(id -un)" "$CLOUDIATOR_HOME" "$(id -un)")"

if [ -f "$NEWSYSLOG_CONF" ] && [ "$(cat "$NEWSYSLOG_CONF")" = "$NEWSYSLOG_BODY" ]; then
  pass "$NEWSYSLOG_CONF is current"
elif printf '%s\n' "$NEWSYSLOG_BODY" | sudo tee "$NEWSYSLOG_CONF" >/dev/null 2>&1; then
  pass "wrote $NEWSYSLOG_CONF"
  sudo newsyslog -nvv >/dev/null 2>&1 && pass "newsyslog parses the config" \
    || warn "newsyslog -nvv reported a problem; run it by hand"
else
  warn "could not write $NEWSYSLOG_CONF (needs sudo). Logs will grow without a bound"
fi

# --------------------------------------------------------------------------
section "Ollama environment (PLAN.md §4)"

# The worker cannot set env for a server that is already running, and Ollama.app
# is a GUI process, so these go through launchctl setenv.
OLLAMA_ENV_OK=1
set_gui_env() {
  launchctl setenv "$1" "$2" >/dev/null 2>&1 || OLLAMA_ENV_OK=0
}
set_gui_env OLLAMA_HOST 127.0.0.1:11434
set_gui_env OLLAMA_MAX_LOADED_MODELS 2
set_gui_env OLLAMA_NUM_PARALLEL 1
set_gui_env OLLAMA_MAX_QUEUE 32
set_gui_env OLLAMA_FLASH_ATTENTION 1
set_gui_env OLLAMA_KEEP_ALIVE 30m
set_gui_env OLLAMA_ORIGINS http://127.0.0.1:8080
if [ "$OLLAMA_ENV_OK" = "1" ]; then
  pass "launchctl setenv applied (slot 1 = one generative model, slot 2 = the embedder)"
  info "quit and reopen Ollama.app so the server picks these up, then re-run scripts/phase-a-gates.sh"
else
  warn "launchctl setenv failed; set the Ollama env by hand (docs/host-setup.md §5)"
fi
info "OLLAMA_KEEP_ALIVE=30m is a safety net only — the worker always sends an explicit keep_alive"

# --------------------------------------------------------------------------
section "Worker virtualenv (Python 3.11 arm64)"

if command -v uv >/dev/null 2>&1; then
  cd "$ROOT/apps/worker" || die "missing $ROOT/apps/worker"
  uv python pin 3.11 >/dev/null 2>&1 && pass "uv python pin 3.11" || warn "uv python pin failed"
  if uv sync --extra dev; then
    pass "uv sync (dependencies and uv.lock)"
  else
    fail "uv sync failed"
  fi
  if [ -x .venv/bin/python ]; then
    VENV_MACHINE="$(.venv/bin/python -c 'import platform;print(platform.machine())' 2>/dev/null)"
    if [ "$VENV_MACHINE" = "arm64" ]; then
      pass "venv is arm64"
    else
      fail "venv reports '$VENV_MACHINE'. rm -rf .venv && uv venv --python /opt/homebrew/opt/python@3.11/bin/python3.11"
    fi
    .venv/bin/python -c 'import Vision' >/dev/null 2>&1 \
      && pass "import Vision works (Phase D OCR)" \
      || warn "import Vision failed. Rebuild against /opt/homebrew/opt/python@3.11/bin/python3.11"

    # tiktoken fetches its BPE table on first use. Do that here, not on the
    # first request: the worker never loads it from a request path, so an
    # un-warmed cache silently downgrades the context guard to a heuristic.
    if .venv/bin/python -c 'from app.context_guard import prewarm_encoder; raise SystemExit(0 if prewarm_encoder() else 1)' >/dev/null 2>&1; then
      pass "tiktoken encoder cached for the context guard"
    else
      warn "could not cache the tiktoken encoder; the context guard falls back to a character heuristic"
    fi
  fi
  cd "$ROOT" || exit 1
else
  fail "uv not on PATH. brew install uv"
fi

if [ -f "$HOME/Cloudiator/.env" ]; then
  pass "$HOME/Cloudiator/.env exists"
  PERMS="$(stat -f '%OLp' "$HOME/Cloudiator/.env" 2>/dev/null)"
  [ "$PERMS" = "600" ] && pass ".env is chmod 600" || warn ".env is mode $PERMS; run chmod 600 ~/Cloudiator/.env"
else
  warn "no ~/Cloudiator/.env yet: cp .env.example ~/Cloudiator/.env && chmod 600 ~/Cloudiator/.env"
  info "the worker refuses to boot unless OLLAMA_MAX_LOADED_MODELS=2 is in that file"
fi

# --------------------------------------------------------------------------
section "Model pulls — Phase A scope only (PLAN.md §7)"

if [ "$SKIP_PULLS" = "1" ]; then
  info "skipped"
elif ! command -v ollama >/dev/null 2>&1; then
  fail "ollama not on PATH; cannot pull"
else
  assert_model_allowed "$DEFAULT_MODEL"
  for model in "$DEFAULT_MODEL" "$EMBED_MODEL"; do
    if ollama show "$model" >/dev/null 2>&1; then
      pass "$model already on disk"
    else
      info "pulling $model"
      ollama pull "$model" && pass "pulled $model" || fail "could not pull $model — see the fallback ladder in PLAN.md §7"
    fi
  done
  if [ "$WITH_FALLBACK" = "1" ]; then
    ollama show llama3.2:3b >/dev/null 2>&1 || ollama pull llama3.2:3b >/dev/null 2>&1
    pass "fallback llama3.2:3b available"
  fi
  info "gpt-oss:20b, gemma4:26b/31b, 27B, 70B, and 120B are NOT pulled here. 20B is Phase E and opt-in."
fi

section "Next"
info "1. scripts/phase-a-gates.sh          # step 0 gates must be green"
info "2. cd apps/worker && uv run pytest -q"
info "3. scripts/install-launchagents.sh   # then scripts/smoke-phase-a.sh"

summary "Host setup"
