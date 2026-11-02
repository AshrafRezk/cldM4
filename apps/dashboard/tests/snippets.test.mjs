import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { apexSnippet, jsonBodyExample } from "../netlify/functions/_lib/salesforce.mjs";
import { mintSecret } from "../netlify/functions/_lib/keys.mjs";
import { installSteps } from "../src/salesforceSnippets.js";

const here = dirname(fileURLToPath(import.meta.url));

test("Apex snippet contains the Salesforce timeout and stream:false", () => {
  const snippet = apexSnippet("https://api.cloudiator.org");
  assert.match(snippet, /setTimeout\(120000\)/);
  assert.match(snippet, /'stream' => false/);
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

test("Console can connect an already-minted sk-cld key without redeploying", () => {
  const panel = readFileSync(join(here, "../src/SalesforcePanel.jsx"), "utf8");
  const install = readFileSync(join(here, "../netlify/functions/_lib/sfInstall.mjs"), "utf8");
  assert.match(panel, /Connect existing key only/);
  assert.match(panel, /configureOnly/);
  assert.match(install, /configureOnly/);
  assert.match(install, /mode: payload\.configureOnly \? "connect" : "install"/);
  const steps = installSteps().join(" ");
  assert.match(steps, /Connect existing key only/);
  assert.match(steps, /existing sk-cld/);
});

test("the built client bundle contains the Apex timeout and stream:false", async () => {
  const { readFileSync, readdirSync } = await import("node:fs");
  const distJs = join(here, "../dist/assets");
  const files = readdirSync(distJs).filter((name) => name.endsWith(".js"));
  const bundled = files.map((name) => readFileSync(join(distJs, name), "utf8")).join("\n");
  assert.match(bundled, /setTimeout\(120000\)/);
  assert.match(bundled, /stream['"]?\s*=>\s*false|stream": false/);
});

test("voice is a Salesforce service, with a body the worker accepts, and the OpenAPI mints call links", async () => {
  const { SERVICES } = await import("../src/salesforceSnippets.js");
  const voice = SERVICES.find((row) => row.id === "voice");
  assert.ok(voice, "voice is listed in the Salesforce tab");
  assert.match(voice.note, /voice scope/);
  assert.deepEqual(voice.body.languages, ["ar-EG", "en-US"]);
  assert.equal(SERVICES.some((row) => row.id === "audio"), false, "no stale 'audio waits on Phase G' entry");
  const { buildOpenApi } = await import("../../../packages/schema/generate.mjs");
  const doc = buildOpenApi(["chat", "voice"], { target: "salesforce", publicBaseUrl: "https://api.cloudiator.org" });
  assert.ok(doc.paths["/v1/voice/scripts/{id}/web-link"].post);
  assert.equal(buildOpenApi(["chat"], { target: "salesforce" }).paths["/v1/voice/scripts"], undefined);
});
