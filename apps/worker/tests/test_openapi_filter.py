"""GET /v1/openapi.json, filtered by the key's scopes (PLAN.md §10).

The generator lives in `packages/schema`; these tests cover the worker's use of
it plus the two properties that decide whether a Salesforce admin can actually
import the document:

* `?target=salesforce` is OpenAPI **3.0.3** restricted to what the External
  Services importer accepts — no composition keywords, no free-form objects, no
  binary or multipart bodies, unique Apex-safe operationIds.
* a key only ever sees operations it has scope for, so a chat-only Salesforce key
  cannot discover image generation.

Verifying the import in Phase B is the point: finding out in Phase F, after the
generator is written, is the expensive version of this lesson.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "packages" / "schema"
if str(SCHEMA_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEMA_DIR))

from generate import build_openapi, composition_keys, load_scopes  # noqa: E402

SALESFORCE_CAPABILITIES = load_scopes()["presets"]["salesforce_engineer"]["capabilities"]


def operation_ids(doc) -> list[str]:
    ids = []
    for item in doc["paths"].values():
        for method, operation in item.items():
            if isinstance(operation, dict) and "operationId" in operation:
                ids.append(operation["operationId"])
    return ids


def media_types(doc) -> set[str]:
    found = set()
    for item in doc["paths"].values():
        for operation in item.values():
            if not isinstance(operation, dict):
                continue
            bodies = [operation.get("requestBody") or {}]
            bodies += list((operation.get("responses") or {}).values())
            for body in bodies:
                found.update((body.get("content") or {}).keys())
    return found


# ---- scope filtering -----------------------------------------------------


def test_a_chat_only_key_sees_neither_embeddings_nor_jobs():
    paths = build_openapi(["chat"])["paths"]

    assert "/v1/chat/completions" in paths
    assert "/v1/embeddings" not in paths
    assert "/v1/jobs" not in paths


def test_health_models_and_usage_are_always_present():
    paths = build_openapi([])["paths"]

    for always in ("/v1/health", "/v1/models", "/v1/openapi.json", "/v1/usage"):
        assert always in paths


def test_health_is_the_only_unauthenticated_operation():
    doc = build_openapi(["chat"])

    assert doc["security"] == [{"bearerAuth": []}]
    assert doc["paths"]["/v1/health"]["get"]["security"] == []
    assert "security" not in doc["paths"]["/v1/chat/completions"]["post"]


def test_an_image_key_sees_the_jobs_api():
    """Images are always a job on this appliance; the contract says so."""
    paths = build_openapi(["chat", "image_generation"])["paths"]

    assert "/v1/jobs" in paths
    assert "/v1/jobs/{id}" in paths


def test_the_server_url_is_the_public_base_url():
    doc = build_openapi(["chat"], public_base_url="https://api.cloudiator.org/")

    assert doc["servers"] == [{"url": "https://api.cloudiator.org"}]


def test_internal_markers_do_not_leak_into_the_document():
    dumped = json.dumps(build_openapi(SALESFORCE_CAPABILITIES))

    assert "x-cloudiator-scope" not in dumped
    assert "x-cloudiator-always" not in dumped


# ---- the Salesforce subset ----------------------------------------------


def test_the_generic_document_is_31_and_the_salesforce_one_is_303():
    assert build_openapi(["chat"])["openapi"] == "3.1.0"
    assert build_openapi(["chat"], target="salesforce")["openapi"] == "3.0.3"


def test_the_salesforce_document_has_no_composition_keywords():
    doc = build_openapi(SALESFORCE_CAPABILITIES, target="salesforce")

    assert composition_keys(doc) == []
    dumped = json.dumps(doc)
    for keyword in ("oneOf", "anyOf", "allOf", '"not"'):
        assert keyword not in dumped


def test_the_salesforce_document_is_json_only():
    """No multipart, no binary: Apex cannot build either inside its heap."""
    doc = build_openapi(SALESFORCE_CAPABILITIES, target="salesforce")

    assert media_types(doc) == {"application/json"}
    assert "binary" not in json.dumps(doc)


def test_the_salesforce_document_has_no_free_form_objects():
    """An untyped object arrives in Apex as an opaque Map nobody can call."""
    doc = build_openapi(SALESFORCE_CAPABILITIES, target="salesforce")

    for name, schema in doc["components"]["schemas"].items():
        assert "additionalProperties" not in schema, name
        if schema.get("type") == "object":
            assert schema.get("properties"), name


def test_salesforce_operation_ids_are_unique_and_apex_safe():
    ids = operation_ids(build_openapi(SALESFORCE_CAPABILITIES, target="salesforce"))

    assert ids
    assert len(ids) == len(set(ids))
    for oid in ids:
        assert oid.isidentifier() and not oid[0].isdigit()


def test_the_salesforce_document_drops_the_openapi_route_itself():
    """Its response is a free-form document, which the importer mangles."""
    doc = build_openapi(SALESFORCE_CAPABILITIES, target="salesforce")

    assert "/v1/openapi.json" not in doc["paths"]
    assert "/v1/openapi.json" in build_openapi(SALESFORCE_CAPABILITIES)["paths"]


def test_every_ref_is_internal_and_resolvable():
    doc = build_openapi(SALESFORCE_CAPABILITIES, target="salesforce")
    schemas = doc["components"]["schemas"]

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref":
                    assert value.startswith("#/components/schemas/"), value
                    assert value.rsplit("/", 1)[1] in schemas, value
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)


def test_a_fragment_that_breaks_the_subset_fails_the_build(monkeypatch):
    """The generator refuses to emit a document that would import badly."""
    import generate

    broken = {
        "x-cloudiator-scope": ["chat"],
        "paths": {},
        "components": {"schemas": {"Loose": {"type": "object"}}},
    }
    monkeypatch.setattr(generate, "_load_fragments", lambda: [broken])

    with pytest.raises(ValueError, match="without properties"):
        generate.build_openapi(["chat"], target="salesforce")


# ---- the HTTP route ------------------------------------------------------


async def test_the_route_serves_the_key_its_own_contract(make_client, install_key):
    _, headers = install_key(capabilities=["chat"])

    async with make_client(headers) as client:
        response = await client.get("/v1/openapi.json")

    body = response.json()
    assert response.status_code == 200
    assert body["openapi"] == "3.1.0"
    assert body["servers"] == [{"url": "https://api.cloudiator.test"}]
    assert "/v1/embeddings" not in body["paths"]


async def test_the_route_serves_the_salesforce_variant(make_client, install_key):
    _, headers = install_key(capabilities=list(SALESFORCE_CAPABILITIES))

    async with make_client(headers) as client:
        response = await client.get("/v1/openapi.json?target=salesforce")

    body = response.json()
    assert body["openapi"] == "3.0.3"
    assert composition_keys(body) == []


async def test_an_unknown_target_is_rejected_loudly(make_client, cached_key):
    _, headers = cached_key

    async with make_client(headers) as client:
        response = await client.get("/v1/openapi.json?target=mulesoft")

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "target"


async def test_the_contract_needs_a_key(make_client):
    async with make_client() as client:
        response = await client.get("/v1/openapi.json")

    assert response.status_code == 401
