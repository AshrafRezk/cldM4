#!/usr/bin/env bash
# Zip Salesforce unmanaged metadata for Workbench / Metadata API deploy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${ROOT}/dist"
OUT_ZIP="${OUT_DIR}/cloudiator-salesforce-unmanaged.zip"
STAGE="${OUT_DIR}/sf-unmanaged-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/unpackaged" "$OUT_DIR"
cp "$ROOT/salesforce/package.xml" "$STAGE/unpackaged/package.xml"
cp -a "$ROOT/salesforce/force-app/main/default/." "$STAGE/unpackaged/"
# Metadata API zip expects package.xml at root of unpackaged
rm -f "$OUT_ZIP"
( cd "$STAGE" && zip -r "$OUT_ZIP" unpackaged >/dev/null )
ls -la "$OUT_ZIP"
echo "Deploy with Workbench → Deploy, or: sf project deploy start --source-dir salesforce/force-app"
