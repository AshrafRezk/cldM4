import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { handler } from "../netlify/functions/api.mjs";
import { useSqlForTests } from "../netlify/functions/_lib/db.mjs";

process.env.ADMIN_SESSION_SECRET = "test-secret-at-least-16";

const TENANT = "11111111-1111-1111-1111-111111111111";
const KEY = "22222222-2222-2222-2222-222222222222";

let queries;
let answers;

/** A fake Neon tagged template: records each query, answers by the first matching pattern. */
function fakeSql(strings, ...values) {
  const text = strings.join("?").replace(/\s+/g, " ").trim();
  queries.push({ text, values });
  const hit = answers.find(([pattern]) => pattern.test(text));
  return Promise.resolve(hit ? hit[1](values) : []);
}

beforeEach(() => {
  queries = [];
  answers = [];
  useSqlForTests(fakeSql);
});

function call(method, path, body) {
  return handler({
    httpMethod: method,
    path: `/api${path}`,
    headers: { "Cf-Access-Authenticated-User-Email": "ops@example.org" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((res) => ({ status: res.statusCode, body: JSON.parse(res.body) }));
}

function keyRow(extra = {}) {
  return {
    id: KEY,
    tenant_id: TENANT,
    public_id: "abc123def456",
    name: "Salesforce org",
    preset: null,
    capabilities: ["chat", "voice"],
    models: [],
    max_tokens: 512,
    max_context: 4096,
    rpm: 30,
    force_no_stream: true,
    log_prompts: false,
    revoked_at: null,
    created_at: "2026-10-01T00:00:00Z",
    ...extra,
  };
}

test("listing keys reports when each was last used, never a secret", async () => {
  answers.push([/FROM api_keys k/, () => [keyRow({ last_used_at: "2026-11-01T09:00:00Z" })]]);
  const res = await call("GET", `/tenants/${TENANT}/keys`);
  assert.equal(res.status, 200);
  assert.equal(res.body.keys[0].lastUsedAt, "2026-11-01T09:00:00Z");
  assert.equal(JSON.stringify(res.body).includes("secret"), false);
  assert.match(queries[0].text, /usage_events/);
});

test("scopes on an existing key can be changed", async () => {
  answers.push([/SELECT preset, name FROM api_keys/, () => [{ preset: "speech", name: "Salesforce org" }]]);
  answers.push([/UPDATE api_keys SET capabilities/, (values) => [keyRow({ capabilities: JSON.parse(values[0]), preset: values[2] })]]);
  const res = await call("PATCH", `/keys/${KEY}`, { capabilities: ["chat", "voice", "embeddings", "chat"] });
  assert.equal(res.status, 200);
  assert.deepEqual(res.body.key.capabilities, ["chat", "voice", "embeddings"]);
  assert.equal(res.body.key.preset, null, "scopes that no longer match the preset drop its label");
  assert.match(res.body.warning, /60 seconds/);
});

test("unknown or empty scopes are refused, and revoked keys cannot be edited", async () => {
  answers.push([/SELECT preset, name FROM api_keys/, () => [{ preset: null, name: "x" }]]);
  assert.equal((await call("PATCH", `/keys/${KEY}`, { capabilities: ["root"] })).status, 400);
  assert.equal((await call("PATCH", `/keys/${KEY}`, { capabilities: [] })).status, 400);
  assert.equal(queries.some((q) => q.text.startsWith("UPDATE")), false);
  answers = [];
  assert.equal((await call("PATCH", `/keys/${KEY}`, { capabilities: ["chat"] })).status, 404);
});

test("deleting a tenant needs its slug, revokes every key and hides it", async () => {
  answers.push([/SELECT id, slug FROM tenants/, () => [{ id: TENANT, slug: "merck-test" }]]);
  answers.push([/UPDATE api_keys SET revoked_at/, () => [{ id: KEY, public_id: "abc123def456" }]]);
  const refused = await call("DELETE", `/tenants/${TENANT}`, { confirm: "wrong" });
  assert.equal(refused.status, 400);
  assert.equal(queries.some((q) => q.text.startsWith("UPDATE")), false);

  const res = await call("DELETE", `/tenants/${TENANT}`, { confirm: "merck-test" });
  assert.equal(res.status, 200);
  assert.deepEqual(res.body.revokedKeys, ["abc123def456"]);
  const updates = queries.filter((q) => q.text.startsWith("UPDATE")).map((q) => q.text);
  assert.match(updates[0], /UPDATE api_keys SET revoked_at = now\(\) WHERE tenant_id/);
  assert.match(updates[1], /UPDATE tenants SET deleted_at = now\(\)/);
});

test("deleted tenants are hidden, and re-creating the slug restores one", async () => {
  await call("GET", "/tenants");
  assert.match(queries[0].text, /WHERE deleted_at IS NULL/);
  answers.push([/INSERT INTO tenants/, () => [{ id: TENANT, slug: "acme", name: "Acme" }]]);
  await call("POST", "/tenants", { slug: "acme", name: "Acme" });
  assert.match(queries[1].text, /deleted_at = NULL/);
});
