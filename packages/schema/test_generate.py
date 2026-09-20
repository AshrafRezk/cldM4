from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent
if str(SCHEMA_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEMA_DIR))

from generate import build_openapi, composition_keys, load_scopes  # noqa: E402


class OpenApiFilterTests(unittest.TestCase):
    def test_chat_only_hides_embeddings_and_jobs(self) -> None:
        doc = build_openapi(["chat"])
        paths = doc["paths"]
        self.assertIn("/v1/chat/completions", paths)
        self.assertIn("/v1/health", paths)
        self.assertIn("/v1/openapi.json", paths)
        self.assertIn("/v1/models", paths)
        self.assertNotIn("/v1/embeddings", paths)
        self.assertNotIn("/v1/jobs", paths)

    def test_embeddings_scope_includes_embeddings(self) -> None:
        doc = build_openapi(["chat", "embeddings"])
        self.assertIn("/v1/embeddings", doc["paths"])
        self.assertNotIn("/v1/jobs", doc["paths"])

    def test_image_generation_includes_jobs(self) -> None:
        doc = build_openapi(["image_generation"])
        self.assertIn("/v1/jobs", doc["paths"])
        self.assertNotIn("/v1/chat/completions", doc["paths"])

    def test_salesforce_target_is_303_without_composition(self) -> None:
        scopes = load_scopes()["presets"]["salesforce_engineer"]["capabilities"]
        doc = build_openapi(scopes, target="salesforce")
        self.assertEqual(doc["openapi"], "3.0.3")
        self.assertEqual(composition_keys(doc), [])
        self.assertIn("/v1/chat/completions", doc["paths"])
        self.assertNotIn("/v1/jobs", doc["paths"])
        ids = []
        for item in doc["paths"].values():
            for op in item.values():
                if isinstance(op, dict) and "operationId" in op:
                    ids.append(op["operationId"])
        self.assertEqual(len(ids), len(set(ids)))
        dumped = json.dumps(doc)
        self.assertNotIn("oneOf", dumped)
        self.assertNotIn("anyOf", dumped)
        self.assertNotIn("allOf", dumped)

    def test_generic_target_is_31(self) -> None:
        doc = build_openapi(["chat"])
        self.assertEqual(doc["openapi"], "3.1.0")

    def test_health_has_no_security(self) -> None:
        doc = build_openapi(["chat"])
        self.assertEqual(doc["paths"]["/v1/health"]["get"]["security"], [])

    def test_the_salesforce_target_drops_fragments_marked_unsafe(self) -> None:
        """Its response is a free-form document; the importer mangles it."""
        scopes = load_scopes()["presets"]["salesforce_engineer"]["capabilities"]

        self.assertIn("/v1/openapi.json", build_openapi(scopes)["paths"])
        self.assertNotIn("/v1/openapi.json", build_openapi(scopes, target="salesforce")["paths"])

    def test_the_salesforce_target_rejects_a_free_form_object(self) -> None:
        import generate

        original = generate._load_fragments
        generate._load_fragments = lambda: [
            {
                "x-cloudiator-scope": ["chat"],
                "paths": {},
                "components": {"schemas": {"Loose": {"type": "object"}}},
            }
        ]
        try:
            with self.assertRaises(ValueError):
                generate.build_openapi(["chat"], target="salesforce")
            # The same fragment is fine for a generic 3.1 client.
            generate.build_openapi(["chat"])
        finally:
            generate._load_fragments = original


if __name__ == "__main__":
    unittest.main()
