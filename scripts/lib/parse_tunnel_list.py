#!/usr/bin/env python3
"""Read `cloudflared tunnel list --output json` and print the UUID for a name.

cloudflared has returned a list, a wrapped object, or JSON `null` (empty).
Iterating `null` is the TypeError that aborted install-tunnel.sh after it had
already created the tunnel.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def tunnels_from_payload(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        inner: Any = data
    elif isinstance(data, dict):
        inner = data.get("tunnels")
        if inner is None:
            inner = data.get("result")
        if isinstance(inner, dict):
            inner = inner.get("tunnels") or inner.get("result") or []
    else:
        return []
    if not isinstance(inner, list):
        return []
    return [row for row in inner if isinstance(row, dict)]


def uuid_for_name(data: Any, name: str) -> str:
    for row in tunnels_from_payload(data):
        if row.get("name") == name and not row.get("deleted_at"):
            return str(row.get("id") or "")
    return ""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: parse_tunnel_list.py <tunnel-name>", file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return 0
    uuid = uuid_for_name(data, args[0])
    if uuid:
        print(uuid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
