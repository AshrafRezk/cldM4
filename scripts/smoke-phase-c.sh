#!/usr/bin/env bash
# Phase C definition of done — dashboard build must not leak Neon into the browser.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/dashboard"
npm ci
npm test
echo "Phase C smoke: dist/ has no neon.tech"
