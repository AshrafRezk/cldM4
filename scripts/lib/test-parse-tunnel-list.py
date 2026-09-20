#!/usr/bin/env python3
"""Proof for scripts/lib/parse_tunnel_list.py. Run: python3 scripts/lib/test-parse-tunnel-list.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_tunnel_list import tunnels_from_payload, uuid_for_name

SAMPLE = {
    "id": "e88624cb-3f03-4578-a38b-a7e3e090c873",
    "name": "cloudiator-mini",
    "deleted_at": None,
}


def main() -> int:
    assert tunnels_from_payload(None) == []
    assert tunnels_from_payload("null") == []
    assert uuid_for_name(None, "cloudiator-mini") == ""
    assert uuid_for_name([], "cloudiator-mini") == ""
    assert uuid_for_name([SAMPLE], "cloudiator-mini") == SAMPLE["id"]
    assert uuid_for_name({"tunnels": [SAMPLE]}, "cloudiator-mini") == SAMPLE["id"]
    assert uuid_for_name({"result": [SAMPLE]}, "cloudiator-mini") == SAMPLE["id"]
    deleted = dict(SAMPLE, deleted_at="2026-01-01T00:00:00Z")
    assert uuid_for_name([deleted], "cloudiator-mini") == ""
    print("PASS parse_tunnel_list.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
