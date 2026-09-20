/**
 * Merge OpenAPI fragments by key scope. Twin of generate.py so the dashboard
 * and the worker emit the same contract (PLAN.md §10). Do not fork the merge
 * rules here without also changing generate.py.
 *
 * Fragments are imported (not read at runtime) so Netlify's esbuild bundle
 * includes them. Sort order matches generate.py's glob of filenames.
 */
import chat from "./fragments/chat.json" with { type: "json" };
import common from "./fragments/common.json" with { type: "json" };
import embeddings from "./fragments/embeddings.json" with { type: "json" };
import health from "./fragments/health.json" with { type: "json" };
import jobs from "./fragments/jobs.json" with { type: "json" };
import models from "./fragments/models.json" with { type: "json" };
import openapi from "./fragments/openapi.json" with { type: "json" };
import usage from "./fragments/usage.json" with { type: "json" };
import scopesJson from "./scopes.json" with { type: "json" };

const FRAGMENTS = [chat, common, embeddings, health, jobs, models, openapi, usage];
const FORBIDDEN_COMPOSITION = ["oneOf", "anyOf", "allOf", "not"];
const APEX_OPERATION_ID = /^[A-Za-z][A-Za-z0-9_]*$/;
const SALESFORCE_MEDIA_TYPE = "application/json";

export function loadScopes() {
  return scopesJson;
}

function loadFragments() {
  return FRAGMENTS;
}

function scopeAllows(fragment, scopes, salesforce) {
  if (salesforce && fragment["x-cloudiator-salesforce"] === false) return false;
  if (fragment["x-cloudiator-always"]) return true;
  const needed = fragment["x-cloudiator-scope"] || [];
  return needed.length > 0 && needed.every((item) => scopes.has(item));
}

function mergeDict(dst, src) {
  for (const [key, value] of Object.entries(src)) {
    if (key.startsWith("x-cloudiator-")) continue;
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      dst[key] &&
      typeof dst[key] === "object" &&
      !Array.isArray(dst[key])
    ) {
      mergeDict(dst[key], value);
    } else {
      dst[key] = structuredClone(value);
    }
  }
}

function collectComposition(node, found) {
  if (node && typeof node === "object" && !Array.isArray(node)) {
    for (const [key, value] of Object.entries(node)) {
      if (FORBIDDEN_COMPOSITION.includes(key)) found.push(key);
      collectComposition(value, found);
    }
  } else if (Array.isArray(node)) {
    for (const item of node) collectComposition(item, found);
  }
}

export function compositionKeys(doc) {
  const found = [];
  collectComposition(doc, found);
  return found;
}

function operationIds(doc) {
  const ids = [];
  for (const pathItem of Object.values(doc.paths || {})) {
    if (!pathItem || typeof pathItem !== "object") continue;
    for (const [method, op] of Object.entries(pathItem)) {
      if (method.startsWith("x-") || !op || typeof op !== "object") continue;
      if (op.operationId) ids.push(op.operationId);
    }
  }
  return ids;
}

function walkSchemas(node, path = "") {
  const out = [];
  if (node && typeof node === "object" && !Array.isArray(node)) {
    if ("type" in node || "$ref" in node || "properties" in node) {
      out.push([path, node]);
    }
    for (const [key, value] of Object.entries(node)) {
      out.push(...walkSchemas(value, path ? `${path}.${key}` : key));
    }
  } else if (Array.isArray(node)) {
    node.forEach((item, index) => {
      out.push(...walkSchemas(item, `${path}[${index}]`));
    });
  }
  return out;
}

function mediaTypes(doc) {
  const found = [];
  for (const pathItem of Object.values(doc.paths || {})) {
    if (!pathItem || typeof pathItem !== "object") continue;
    for (const operation of Object.values(pathItem)) {
      if (!operation || typeof operation !== "object") continue;
      const bodies = [operation.requestBody || {}];
      bodies.push(...Object.values(operation.responses || {}));
      for (const body of bodies) {
        if (body && typeof body === "object") {
          found.push(...Object.keys(body.content || {}));
        }
      }
    }
  }
  return found;
}

function assertSalesforceSafe(doc) {
  const bad = compositionKeys(doc);
  if (bad.length) {
    throw new Error(`Salesforce OAS forbids composition keywords: ${[...new Set(bad)].sort()}`);
  }
  const ids = operationIds(doc);
  if (ids.length !== new Set(ids).size) {
    throw new Error("operationId values must be unique");
  }
  for (const oid of ids) {
    if (!APEX_OPERATION_ID.test(oid)) {
      throw new Error(`operationId is not Apex-safe: ${JSON.stringify(oid)}`);
    }
  }
  for (const mediaType of mediaTypes(doc)) {
    if (mediaType !== SALESFORCE_MEDIA_TYPE) {
      throw new Error(`Salesforce OAS is ${SALESFORCE_MEDIA_TYPE} only, found ${JSON.stringify(mediaType)}`);
    }
  }
  for (const [where, schema] of walkSchemas((doc.components || {}).schemas || {})) {
    if ("additionalProperties" in schema) {
      throw new Error(`free-form additionalProperties at ${where}`);
    }
    if (schema.format === "binary") {
      throw new Error(`format: binary is not importable, at ${where}`);
    }
    if ("$ref" in schema) {
      const ref = schema.$ref;
      if (!String(ref).startsWith("#/")) {
        throw new Error(`external $ref at ${where}: ${ref}`);
      }
      continue;
    }
    if (schema.type === "object" && !schema.properties) {
      throw new Error(`object schema without properties at ${where}`);
    }
    if (schema.type === "array" && !schema.items) {
      throw new Error(`array schema without items at ${where}`);
    }
  }
}

export function buildOpenApi(
  scopes,
  { target = null, publicBaseUrl = "https://api.example.com", version = "0.1.0" } = {},
) {
  const scopeSet = new Set(scopes);
  const isSalesforce = String(target || "").toLowerCase() === "salesforce";
  const merged = { paths: {}, components: { schemas: {} } };
  for (const fragment of loadFragments()) {
    if (!scopeAllows(fragment, scopeSet, isSalesforce)) continue;
    mergeDict(merged, fragment);
  }

  const doc = {
    openapi: isSalesforce ? "3.0.3" : "3.1.0",
    info: {
      title: "Cloudiator",
      version,
      description: "Scoped OpenAI-compatible appliance API",
    },
    servers: [{ url: publicBaseUrl.replace(/\/$/, "") }],
    paths: merged.paths || {},
    components: merged.components || {},
    security: [{ bearerAuth: [] }],
  };
  const health = doc.paths["/v1/health"]?.get;
  if (health && typeof health === "object") {
    health.security = [];
  }
  if (isSalesforce) assertSalesforceSafe(doc);
  return doc;
}

export function dumpOpenApi(scopes, options) {
  return `${JSON.stringify(buildOpenApi(scopes, options), null, 2)}\n`;
}
