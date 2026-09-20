"""Phase B OpenAPI filter tests. The generator lives in packages/schema."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "packages" / "schema"
if str(SCHEMA_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEMA_DIR))

from generate import build_openapi, composition_keys  # noqa: E402


class TestOpenapiFilter(unittest.TestCase):
    def test_chat_only_key_omits_flux_jobs(self) -> None:
        doc = build_openapi(["chat"], target="salesforce")
        self.assertEqual(doc["openapi"], "3.0.3")
        self.assertNotIn("/v1/jobs", doc["paths"])
        self.assertEqual(composition_keys(doc), [])


if __name__ == "__main__":
    unittest.main()
