# shellcheck shell=bash
# Shared helpers for the Cloudiator operator scripts.
# macOS ships bash 3.2: no associative arrays, no ${var,,}.

CLD_PASS=0
CLD_FAIL=0
CLD_WARN=0

if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_BOLD=''; C_OFF=''
fi

section() { printf '\n%s== %s ==%s\n' "$C_BOLD$C_BLUE" "$1" "$C_OFF"; }
pass()    { CLD_PASS=$((CLD_PASS + 1)); printf '%sPASS%s %s\n' "$C_GREEN" "$C_OFF" "$1"; }
fail()    { CLD_FAIL=$((CLD_FAIL + 1)); printf '%sFAIL%s %s\n' "$C_RED" "$C_OFF" "$1"; }
warn()    { CLD_WARN=$((CLD_WARN + 1)); printf '%sWARN%s %s\n' "$C_YELLOW" "$C_OFF" "$1"; }
info()    { printf '     %s\n' "$1"; }
die()     { printf '%sABORT%s %s\n' "$C_RED" "$C_OFF" "$1" >&2; exit 1; }

summary() {
  printf '\n%s%s: %d passed, %d failed, %d warnings%s\n' \
    "$C_BOLD" "$1" "$CLD_PASS" "$CLD_FAIL" "$CLD_WARN" "$C_OFF"
  if [ "$CLD_FAIL" -gt 0 ]; then
    printf '%sNot green. Fix the failures above before moving on.%s\n' "$C_RED" "$C_OFF"
    return 1
  fi
  return 0
}

repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

# PLAN.md §5: pyobjc Vision and MLX under Rosetta are broken or pointlessly
# slow, and the failure surfaces much later as "OCR is mysteriously broken".
require_arm64_macos() {
  [ "$(uname -s)" = "Darwin" ] || die "This script runs on the Mac Mini. Detected $(uname -s)."
  if [ "$(uname -m)" != "arm64" ]; then
    die "uname -m is $(uname -m), expected arm64. Terminal or Homebrew is running under Rosetta (PLAN.md §5)."
  fi
  if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; then
    die "This shell is translated by Rosetta. Uncheck 'Open using Rosetta' on Terminal (PLAN.md §5)."
  fi
}

# Models that do not fit the 18 GB ceiling, and the Phase E model, must never be
# pulled by a setup script (PLAN.md §7).
assert_model_allowed() {
  lower="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$lower" in
    gemma4|gemma4:latest)
      die "Refusing '$1'. That is the ~9.6 GB Q4_K_M tag. Pin gemma4:e4b-it-qat (PLAN.md §7)."
      ;;
    *:26b*|*:31b*|*:20b*|*:27b*|*:70b*|*:72b*|*:120b*|*-mlx|*:mlx|*-q8_0*|*-bf16*)
      die "Refusing to pull '$1'. 20B is exclusive-slot, Phase E, and opt-in; 26B/31B/27B/70B/120B, MLX, Q8, and bf16 exceed the 18 GB ceiling or break Gemma 4 prefix cache (PLAN.md §7)."
      ;;
  esac
}

# Octal permissions of a file. BSD stat and GNU stat disagree about -f, and GNU
# `stat -f` succeeds with filesystem information rather than failing, so a
# `||` fallback silently prints the wrong thing.
file_mode() {
  if [ "$(uname -s)" = "Darwin" ]; then
    stat -f '%Lp' "$1" 2>/dev/null
  else
    stat -c '%a' "$1" 2>/dev/null
  fi
}

# KEY=VALUE parser — never `source` the file. Unquoted parentheses in
# NOMINATIM_USER_AGENT are a zsh parse error and would abort every script here
# plus the LaunchAgent wrapper. See scripts/lib/load-env.sh.
# shellcheck source=load-env.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/load-env.sh"
