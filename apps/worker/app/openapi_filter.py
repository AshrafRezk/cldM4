"""Per-key OpenAPI documents (PLAN.md §10).

The generator lives in `packages/schema` because the dashboard and the CLI need
it too. `generate.py` is what the worker loads by path; `generate.mjs` is the
Netlify twin. Keep them in lockstep — two merge implementations is how a key
ends up with a contract it cannot call.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

from .errors import CloudiatorError

log = logging.getLogger("cloudiator.openapi")

# apps/worker/app/openapi_filter.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCHEMA_DIR = REPO_ROOT / "packages" / "schema"

_module: ModuleType | None = None


def schema_dir() -> Path:
    override = os.environ.get("SCHEMA_DIR")
    return Path(override).expanduser() if override else DEFAULT_SCHEMA_DIR


def load_generator() -> ModuleType:
    global _module
    if _module is not None:
        return _module
    path = schema_dir() / "generate.py"
    if not path.is_file():
        raise CloudiatorError(
            503,
            "not_supported",
            f"The OpenAPI fragments are missing from this checkout ({path}). "
            "Set SCHEMA_DIR or restore packages/schema.",
            error_type="server_error",
        )
    spec = importlib.util.spec_from_file_location("cloudiator_schema_generate", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise CloudiatorError(
            503, "not_supported", f"Could not load {path}.", error_type="server_error"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _module = module
    return module


def reset_generator_cache() -> None:
    global _module
    _module = None


def build_for_key(
    capabilities: Iterable[str],
    *,
    target: str | None,
    public_base_url: str,
    version: str,
) -> dict[str, Any]:
    generator = load_generator()
    try:
        return generator.build_openapi(
            capabilities,
            target=target,
            public_base_url=public_base_url,
            version=version,
        )
    except ValueError as exc:
        # A fragment broke the Salesforce subset. Better a loud 500 here than an
        # External Services import that half-works in somebody's org.
        log.error("the generated OpenAPI document is not importable: %s", exc)
        raise CloudiatorError(
            500,
            "not_supported",
            "The OpenAPI document for this key could not be generated.",
            error_type="server_error",
        ) from exc


def normalize_target(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    target = value.strip().lower()
    if target != "salesforce":
        raise CloudiatorError(
            400,
            "not_supported",
            f"target={value!r} is not supported. Omit it for OpenAPI 3.1, or use "
            "target=salesforce for the External Services 3.0.3 subset.",
            param="target",
        )
    return target
