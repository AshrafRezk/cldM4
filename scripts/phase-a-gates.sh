#!/usr/bin/env bash
# Phase A STEP 0 gates (docs/cursor-phases.md) plus the Phase 0 hardware checks
# from docs/hardware-and-network.md that Phase A silently depends on.
#
# Run this on the Mac Mini before any application code is trusted. Nothing here
# writes to the system; it only reports.
#
#   scripts/phase-a-gates.sh            # gate c pulls the default model if missing
#   scripts/phase-a-gates.sh --no-pull  # report only, never download
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DO_PULL=1
[ "${1:-}" = "--no-pull" ] && DO_PULL=0

load_env_file "$HOME/Cloudiator/.env"
DEFAULT_MODEL="${DEFAULT_MODEL:-qwen3.5:9b}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
VENV="$ROOT/apps/worker/.venv"

printf '%sCloudiator Phase A gates%s  (model: %s)\n' "$C_BOLD" "$C_OFF" "$DEFAULT_MODEL"

# --------------------------------------------------------------------------
section "Phase 0 — hardware and host (docs/hardware-and-network.md)"

if [ "$(uname -s)" = "Darwin" ]; then
  pass "macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"
else
  fail "not macOS ($(uname -s)); the worker, Metal, and the LaunchAgents only exist on the Mini"
fi

CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo unknown)"
MEM_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
MEM_GB=$((MEM_BYTES / 1024 / 1024 / 1024))
case "$CHIP" in
  *M4*) pass "chip: $CHIP" ;;
  *)    warn "chip reports '$CHIP'; this plan is written for an M4" ;;
esac
if [ "$MEM_GB" -ge 24 ]; then
  pass "memory: ${MEM_GB} GB"
elif [ "$MEM_GB" -ge 16 ]; then
  fail "memory: ${MEM_GB} GB. 16 GB is a different product; do not follow this repo on it"
else
  warn "memory: could not read hw.memsize"
fi

FREE_GB="$(df -g / 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "${FREE_GB:-}" ]; then
  if [ "$FREE_GB" -ge 120 ]; then
    pass "disk: ${FREE_GB} GB free"
  elif [ "$FREE_GB" -ge 80 ]; then
    warn "disk: ${FREE_GB} GB free. Under 120 GB — plan to skip FLUX 8-bit and gpt-oss:20b"
  else
    fail "disk: ${FREE_GB} GB free. A full SSD takes down Ollama, the worker, and the tunnel at once"
  fi
  info "write this number into docs/operator-checklist.md §0"
else
  warn "disk: could not read df -g /"
fi

SWAP_USED="$(sysctl -n vm.swapusage 2>/dev/null | sed -n 's/.*used = \([0-9.]*\)M.*/\1/p')"
if [ -n "${SWAP_USED:-}" ]; then
  case "$SWAP_USED" in
    0.00|0) pass "swap: 0.00M used" ;;
    *)      warn "swap: ${SWAP_USED}M already in use before any model is loaded" ;;
  esac
fi

SLEEP_LINE="$(pmset -g 2>/dev/null | awk '$1=="sleep"{print $2; exit}')"
if [ -z "${SLEEP_LINE:-}" ]; then
  warn "energy: could not read the sleep setting from pmset -g"
elif [ "$SLEEP_LINE" = "0" ]; then
  pass "energy: computer sleep is disabled"
else
  warn "energy: computer sleep is ${SLEEP_LINE}. System Settings → Energy: prevent sleeping when the display is off. Cursor cannot fix a sleeping origin"
fi

if systemsetup -getusingnetworktime 2>/dev/null | grep -qi "on"; then
  pass "network time is on"
else
  warn "could not confirm automatic time. Artifact URL signatures expire against this clock"
fi

# This install is Wi-Fi (see docs/hardware-and-network.md §3). One uplink only:
# two active interfaces cause flaky tunnel reconnects.
ACTIVE_IFS=""
for iface in $(networksetup -listallhardwareports 2>/dev/null | awk '/Device:/{print $2}'); do
  if ifconfig "$iface" 2>/dev/null | grep -q "status: active"; then
    ACTIVE_IFS="$ACTIVE_IFS $iface"
  fi
done
ACTIVE_COUNT="$(printf '%s' "$ACTIVE_IFS" | wc -w | tr -d ' ')"
if [ "$ACTIVE_COUNT" = "1" ]; then
  pass "uplink: exactly one active interface ($(printf '%s' "$ACTIVE_IFS" | tr -d ' '))"
elif [ "$ACTIVE_COUNT" = "0" ]; then
  warn "uplink: no active interface detected"
else
  warn "uplink:$ACTIVE_IFS are both active. Turn one off — two interfaces flap the tunnel"
fi

# --------------------------------------------------------------------------
section "Gate a — architecture must be arm64 everywhere (PLAN.md §5)"

if [ "$(uname -m)" = "arm64" ]; then
  pass "uname -m = arm64"
else
  fail "uname -m = $(uname -m). Abort the phase (PLAN.md §5)"
fi

if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; then
  fail "this shell is translated by Rosetta. Uncheck 'Open using Rosetta' on Terminal"
else
  pass "shell is not translated by Rosetta"
fi

if command -v python3.11 >/dev/null 2>&1; then
  PY_MACHINE="$(python3.11 -c 'import platform;print(platform.machine())' 2>/dev/null)"
  if [ "$PY_MACHINE" = "arm64" ]; then
    pass "python3.11 reports arm64"
  else
    fail "python3.11 reports '$PY_MACHINE'. Rebuild against /opt/homebrew/opt/python@3.11/bin/python3.11"
  fi
  if file "$(command -v python3.11)" 2>/dev/null | grep -q arm64; then
    pass "python3.11 binary is arm64"
  else
    fail "python3.11 binary is not arm64: $(file "$(command -v python3.11)" | head -1)"
  fi
else
  fail "python3.11 not on PATH. brew install python@3.11"
fi

if command -v brew >/dev/null 2>&1; then
  if file "$(command -v brew)" 2>/dev/null | grep -q "arm64\|script text"; then
    pass "brew is the arm64 install ($(command -v brew))"
  else
    warn "could not confirm brew architecture"
  fi
else
  fail "brew not on PATH"
fi

# --------------------------------------------------------------------------
section "Gate b — only the official Ollama.app owns 11434 (PLAN.md §7)"

if command -v brew >/dev/null 2>&1 && brew list 2>/dev/null | grep -qi '^ollama$'; then
  fail "brew ollama is installed. Two servers fight over 11434 and the brew one starts without the LaunchAgent env: brew uninstall ollama"
else
  pass "no brew ollama"
fi

if [ -d "/Applications/Ollama.app" ]; then
  pass "Ollama.app is installed"
else
  fail "Ollama.app is missing: open https://ollama.com/download/mac"
fi

if command -v ollama >/dev/null 2>&1; then
  pass "ollama on PATH ($(command -v ollama))"
else
  fail "ollama not on PATH"
fi

if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  pass "Ollama answers on 127.0.0.1:11434"
else
  fail "no answer from 127.0.0.1:11434. Start Ollama.app"
fi

LISTENERS="$(lsof -nP -iTCP:11434 -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sort -u)"
if [ -n "$LISTENERS" ]; then
  if printf '%s\n' "$LISTENERS" | grep -qv '^127\.0\.0\.1:\|^\[::1\]:'; then
    fail "11434 is bound beyond loopback: $LISTENERS. Rotate every sk-cld- key if this was ever reachable"
  else
    pass "11434 is loopback only"
  fi
fi

if [ "${OLLAMA_MAX_LOADED_MODELS:-}" = "2" ]; then
  pass "OLLAMA_MAX_LOADED_MODELS=2 in this shell"
else
  warn "OLLAMA_MAX_LOADED_MODELS is '${OLLAMA_MAX_LOADED_MODELS:-unset}' in this shell; the worker refuses to boot unless it is 2 (PLAN.md §4)"
fi

# --------------------------------------------------------------------------
section "Gate c — model tag verification (PLAN.md §7)"

if command -v ollama >/dev/null 2>&1; then
  assert_model_allowed "$DEFAULT_MODEL"
  if ! ollama show "$DEFAULT_MODEL" >/dev/null 2>&1 && [ "$DO_PULL" = "1" ]; then
    info "pulling $DEFAULT_MODEL (this is the ~6.6 GB download; Wi-Fi makes it slower)"
    ollama pull "$DEFAULT_MODEL" || true
  fi

  if SHOW="$(ollama show "$DEFAULT_MODEL" 2>/dev/null)"; then
    pass "tag resolves: $DEFAULT_MODEL"
    if printf '%s' "$SHOW" | tr '[:upper:]' '[:lower:]' | grep -q "tools"; then
      pass "$DEFAULT_MODEL supports tools (the Phase D registry depends on it)"
    else
      fail "$DEFAULT_MODEL does not advertise tool support. The tool registry needs it"
    fi
    if printf '%s' "$SHOW" | tr '[:upper:]' '[:lower:]' | grep -q "vision"; then
      pass "$DEFAULT_MODEL supports vision — set DEFAULT_MODEL_HAS_VISION=true in .env"
    else
      info "no vision capability: the image path is OCR-only and chat with an image_url returns"
      info "model_not_found. That is an acceptable v1 (PLAN.md §7). Record it in checklist §8."
    fi
  else
    fail "tag does not resolve: $DEFAULT_MODEL"
    info "Walk the ladder in PLAN.md §7 and take the first that resolves, supports tools, and fits 6-9 GB:"
    info "  1. the current qwen3.5 tag in the 7-9B range on https://ollama.com/library/qwen3.5"
    info "  2. qwen3:8b    3. qwen2.5:7b-instruct    4. llama3.1:8b"
    info "Then set DEFAULT_MODEL in ~/Cloudiator/.env, record it in docs/operator-checklist.md §8,"
    info "and change nothing else. Do not substitute a 27B or a 14B."
    info "STOP and confirm the choice before continuing Phase A."
  fi

  if ollama show "$EMBED_MODEL" >/dev/null 2>&1; then
    pass "embedder on disk: $EMBED_MODEL"
  elif [ "$DO_PULL" = "1" ]; then
    info "pulling $EMBED_MODEL (~274 MB)"
    ollama pull "$EMBED_MODEL" >/dev/null 2>&1 && pass "pulled $EMBED_MODEL" || fail "could not pull $EMBED_MODEL"
  else
    fail "embedder missing: $EMBED_MODEL"
  fi

  RESIDENT="$(ollama ps 2>/dev/null | awk 'NR>1{print $1}')"
  GENERATIVE=0
  for name in $RESIDENT; do
    case "$name" in
      "$EMBED_MODEL"|"$EMBED_MODEL":latest|nomic-embed-text|nomic-embed-text:latest) ;;
      *) GENERATIVE=$((GENERATIVE + 1)) ;;
    esac
  done
  if [ "$GENERATIVE" -le 1 ]; then
    pass "ollama ps: $GENERATIVE generative model resident"
  else
    fail "ollama ps: $GENERATIVE generative models resident. That is a phase failure, not a warning (PLAN.md §4)"
  fi
fi

# --------------------------------------------------------------------------
section "Gate d — Apple Vision imports in the worker venv (Phase D depends on it)"

if [ -x "$VENV/bin/python" ]; then
  VENV_MACHINE="$("$VENV/bin/python" -c 'import platform;print(platform.machine())' 2>/dev/null)"
  if [ "$VENV_MACHINE" = "arm64" ]; then
    pass "venv python is arm64"
  else
    fail "venv python reports '$VENV_MACHINE'. rm -rf apps/worker/.venv and re-run scripts/mac-setup.sh"
  fi
  VENV_PY="$("$VENV/bin/python" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  if [ "$VENV_PY" = "3.11" ]; then
    pass "venv python is 3.11"
  else
    fail "venv python is $VENV_PY, expected 3.11"
  fi
  if "$VENV/bin/python" -c 'import Vision' >/dev/null 2>&1; then
    pass "import Vision works"
  else
    fail "import Vision failed. Rebuild the venv against Homebrew's framework Python: uv venv --python /opt/homebrew/opt/python@3.11/bin/python3.11"
  fi
else
  fail "no venv at $VENV. Run scripts/mac-setup.sh first"
fi

summary "Phase A gates"
