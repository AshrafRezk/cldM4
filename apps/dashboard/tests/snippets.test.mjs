import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { apexSnippet, jsonBodyExample } from "../netlify/functions/_lib/salesforce.mjs";
import { mintSecret } from "../netlify/functions/_lib/keys.mjs";

const here = dirname(fileURLToPath(import.meta.url));

test("Apex snippet contains the Salesforce timeout and stream:false", () => {
  const snippet = apexSnippet("https://api.cloudiator.org");
  assert.match(snippet, /req\.setTimeout\(120000\)/);
  assert.match(snippet, /'stream' => false/);
  assert.match(snippet, /"stream": false/);
});

test("JSON example sent by Apex/playground forces stream false", () => {
  const body = jsonBodyExample();
  assert.match(body, /"stream": false/);
  assert.equal(JSON.parse(body).stream, false);
});

test("minted keys match sk-cld-{public_id}_{secret}", () => {
  const { publicId, secret, plaintext } = mintSecret();
  assert.equal(publicId.length, 12);
  assert.match(publicId, /^[abcdefghijkmnopqrstuvwxyz23456789]+$/);
  assert.equal(plaintext, `sk-cld-${publicId}_${secret}`);
});

test("the client playground calls the Mini API, not a Netlify inference function", () => {
  const src = readFileSync(join(here, "../src/Playground.jsx"), "utf8");
  assert.match(src, /\$\{apiUrl\}\/v1\/chat\/completions/);
  assert.equal(src.includes("ollama"), false);
  assert.equal(src.includes("11434"), false);
});

test("the built client bundle contains the Apex timeout and stream:false", async () => {
  const { readFileSync, readdirSync } = await import("node:fs");
  const distJs = join(here, "../dist/assets");
  const files = readdirSync(distJs).filter((name) => name.endsWith(".js"));
  const bundled = files.map((name) => readFileSync(join(distJs, name), "utf8")).join("\n");
  assert.match(bundled, /setTimeout\(120000\)/);
  assert.match(bundled, /"stream": false/);
});
