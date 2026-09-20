"""Merge OpenAPI fragments by key scope. No Ollama, no Neon, no FastAPI."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

FRAGMENTS_DIR = Path(__file__).resolve().parent / "fragments"
SCOPES_PATH = Path(__file__).resolve().parent / "scopes.json"

FORBIDDEN_COMPOSITION = ("oneOf", "anyOf", "allOf", "not")
APEX_OPERATION_ID = __import__("re").compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def load_scopes() -> dict[str, Any]:
    return json.loads(SCOPES_PATH.read_text())


def _load_fragments() -> list[dict[str, Any]]:
    files = sorted(FRAGMENTS_DIR.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no OpenAPI fragments in {FRAGMENTS_DIR}")
    return [json.loads(path.read_text()) for path in files]


def _scope_allows(fragment: Mapping[str, Any], scopes: set[str]) -> bool:
    if fragment.get("x-cloudiator-always"):
        return True
    needed = fragment.get("x-cloudiator-scope") or []
    return bool(needed) and set(needed).issubset(scopes)


def _merge_dict(dst: dict[str, Any], src: Mapping[str, Any]) -> None:
    for key, value in src.items():
        if key.startswith("x-cloudiator-"):
            continue
        if isinstance(value, Mapping) and isinstance(dst.get(key), dict):
            _merge_dict(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)


def _collect_composition(node: Any, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN_COMPOSITION:
                found.append(key)
            _collect_composition(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_composition(item, found)


def composition_keys(doc: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    _collect_composition(doc, found)
    return found


def _operation_ids(doc: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for path_item in (doc.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            oid = op.get("operationId")
            if oid:
                ids.append(oid)
    return ids


def _assert_salesforce_safe(doc: Mapping[str, Any]) -> None:
    bad = composition_keys(doc)
    if bad:
        raise ValueError(f"Salesforce OAS forbids composition keywords: {sorted(set(bad))}")
    ids = _operation_ids(doc)
    if len(ids) != len(set(ids)):
        raise ValueError("operationId values must be unique")
    for oid in ids:
        if not APEX_OPERATION_ID.match(oid):
            raise ValueError(f"operationId is not Apex-safe: {oid!r}")


def build_openapi(
    scopes: Iterable[str],
    *,
    target: str | None = None,
    public_base_url: str = "https://api.example.com",
    version: str = "0.1.0",
) -> dict[str, Any]:
    """Return an OpenAPI document for the given key scopes.

    target='salesforce' emits OpenAPI 3.0.3 with the restricted subset
    External Services will import (PLAN.md §10).
    """
    scope_set = set(scopes)
    merged: dict[str, Any] = {"paths": {}, "components": {"schemas": {}}}
    for fragment in _load_fragments():
        if not _scope_allows(fragment, scope_set):
            continue
        _merge_dict(merged, fragment)

    is_salesforce = (target or "").lower() == "salesforce"
    doc: dict[str, Any] = {
        "openapi": "3.0.3" if is_salesforce else "3.1.0",
        "info": {
            "title": "Cloudiator",
            "version": version,
            "description": "Scoped OpenAI-compatible appliance API",
        },
        "servers": [{"url": public_base_url.rstrip("/")}],
        "paths": merged.get("paths") or {},
        "components": merged.get("components") or {},
        "security": [{"bearerAuth": []}],
    }
    if "/v1/health" in doc["paths"]:
        health = doc["paths"]["/v1/health"].get("get")
        if isinstance(health, dict):
            health["security"] = []

    if is_salesforce:
        _assert_salesforce_safe(doc)
    return doc


def dump_openapi(scopes: Iterable[str], **kwargs: Any) -> str:
    return json.dumps(build_openapi(scopes, **kwargs), indent=2) + "\n"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build a filtered OpenAPI document")
    parser.add_argument(
        "--scopes",
        default="chat",
        help="comma-separated capabilities (default: chat)",
    )
    parser.add_argument("--target", default="", help="salesforce for 3.0.3 subset")
    parser.add_argument("--base-url", default="https://api.example.com")
    args = parser.parse_args()
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    print(
        dump_openapi(
            scopes,
            target=args.target or None,
            public_base_url=args.base_url,
        ),
        end="",
    )
