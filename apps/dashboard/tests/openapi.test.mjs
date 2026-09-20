import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { buildOpenApi, loadScopes } from "../../../packages/schema/generate.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const schemaDir = join(here, "../../../packages/schema");

test("salesforce target is 3.0.3 without composition keywords", () => {
  const scopes = loadScopes().presets.salesforce_engineer.capabilities;
  const doc = buildOpenApi(scopes, {
    target: "salesforce",
    publicBaseUrl: "https://api.cloudiator.org",
  });
  assert.equal(doc.openapi, "3.0.3");
  assert.ok(doc.paths["/v1/chat/completions"]);
  assert.equal(doc.paths["/v1/openapi.json"], undefined);
  const dumped = JSON.stringify(doc);
  assert.equal(dumped.includes("oneOf"), false);
  assert.equal(dumped.includes("anyOf"), false);
  assert.equal(dumped.includes("allOf"), false);
});

test("JS generator matches Python generate.py for the Salesforce preset", () => {
  const py = execFileSync(
    "python3",
    [
      join(schemaDir, "generate.py"),
      "--scopes",
      "chat,embeddings,tools.ocr,tools.maps,tools.charts,tools.stats,tools.data,tools.docs,tools.text,tools.time,tools.image_ops",
      "--target",
      "salesforce",
      "--base-url",
      "https://api.cloudiator.org",
    ],
    { encoding: "utf8" },
  );
  const js = buildOpenApi(
    [
      "chat",
      "embeddings",
      "tools.ocr",
      "tools.maps",
      "tools.charts",
      "tools.stats",
      "tools.data",
      "tools.docs",
      "tools.text",
      "tools.time",
      "tools.image_ops",
    ],
    { target: "salesforce", publicBaseUrl: "https://api.cloudiator.org" },
  );
  assert.deepEqual(JSON.parse(py), js);
});
