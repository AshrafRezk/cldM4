/**
 * Dashboard API. Talks to Neon. Never calls Ollama. Never proxies inference.
 *
 * Auth: Cloudflare Access email header. See _lib/access.mjs.
 */
import { identify } from "./_lib/access.mjs";
import { dashboardOrigin, publicApiUrl, sql } from "./_lib/db.mjs";
import { httpError, json, readJson, routePath } from "./_lib/http.mjs";
import { hashSecret, mintSecret, parsePreset } from "./_lib/keys.mjs";
import { apexSnippet, DEFAULT_MODEL, jsonBodyExample, namedCredentialSteps } from "./_lib/salesforce.mjs";
import { buildOpenApi, loadScopes } from "./_lib/schema.mjs";

const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,62}$/;
const KNOWN_CAPABILITIES = new Set();

function ok(body, cookie) {
  return json(200, body, cookie ? { "Set-Cookie": cookie } : {});
}

function created(body, cookie) {
  return json(201, body, cookie ? { "Set-Cookie": cookie } : {});
}

async function knownCapabilities() {
  if (KNOWN_CAPABILITIES.size) return KNOWN_CAPABILITIES;
  const scopes = await loadScopes();
  for (const item of scopes.capabilities || []) KNOWN_CAPABILITIES.add(item);
  return KNOWN_CAPABILITIES;
}

function asList(value) {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch {
      return [];
    }
  }
  return [];
}

function publicKey(row) {
  return {
    id: row.id,
    tenantId: row.tenant_id,
    publicId: row.public_id,
    name: row.name,
    preset: row.preset,
    capabilities: asList(row.capabilities),
    models: asList(row.models),
    maxTokens: row.max_tokens,
    maxContext: row.max_context,
    rpm: row.rpm,
    forceNoStream: Boolean(row.force_no_stream),
    logPrompts: Boolean(row.log_prompts),
    revokedAt: row.revoked_at,
    createdAt: row.created_at,
  };
}

async function handle(event) {
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers: { "Access-Control-Allow-Methods": "GET, POST, OPTIONS" } };
  }

  const { email, cookie } = identify(event);
  const path = routePath(event);
  const method = event.httpMethod;
  const db = sql();
  const apiUrl = publicApiUrl();

  if (method === "GET" && path === "/me") {
    return ok(
      {
        email,
        apiUrl,
        defaultModel: process.env.DEFAULT_MODEL || DEFAULT_MODEL,
        revocationLagSeconds: 60,
      },
      cookie,
    );
  }

  if (method === "GET" && path === "/scopes") {
    const scopes = await loadScopes();
    return ok({ capabilities: scopes.capabilities, presets: scopes.presets }, cookie);
  }

  if (method === "GET" && path === "/salesforce-snippet") {
    return ok(
      {
        namedCredential: namedCredentialSteps(apiUrl),
        apex: apexSnippet(apiUrl, process.env.DEFAULT_MODEL || DEFAULT_MODEL),
        jsonBody: jsonBodyExample(process.env.DEFAULT_MODEL || DEFAULT_MODEL),
      },
      cookie,
    );
  }

  if (method === "GET" && path === "/tenants") {
    const rows = await db`
      SELECT id, slug, name, created_at
      FROM tenants
      ORDER BY created_at DESC
    `;
    return ok({ tenants: rows }, cookie);
  }

  if (method === "POST" && path === "/tenants") {
    const body = readJson(event);
    const slug = String(body.slug || "")
      .trim()
      .toLowerCase();
    const name = String(body.name || slug).trim();
    if (!SLUG_RE.test(slug)) {
      throw httpError(400, "Tenant slug must be lowercase letters, digits, and hyphens.");
    }
    if (!name) throw httpError(400, "Tenant name is required.");
    const rows = await db`
      INSERT INTO tenants (slug, name) VALUES (${slug}, ${name})
      ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
      RETURNING id, slug, name, created_at
    `;
    return created({ tenant: rows[0] }, cookie);
  }

  const tenantKeys = path.match(/^\/tenants\/([^/]+)\/keys$/);
  if (tenantKeys && method === "GET") {
    const tenantId = tenantKeys[1];
    const rows = await db`
      SELECT id, tenant_id, public_id, name, preset, capabilities, models, max_tokens,
             max_context, rpm, force_no_stream, log_prompts, revoked_at, created_at
      FROM api_keys
      WHERE tenant_id = ${tenantId}::uuid
      ORDER BY created_at DESC
    `;
    return ok({ keys: rows.map(publicKey) }, cookie);
  }

  if (tenantKeys && method === "POST") {
    const tenantId = tenantKeys[1];
    const body = readJson(event);
    const tenants = await db`SELECT id FROM tenants WHERE id = ${tenantId}::uuid`;
    if (!tenants.length) throw httpError(404, "Tenant not found.");

    const scopes = await loadScopes();
    const allowed = await knownCapabilities();
    const presetName = body.preset ? String(body.preset) : null;
    const preset = parsePreset(scopes, presetName);
    if (presetName && !preset) {
      throw httpError(400, `Unknown preset ${presetName}.`);
    }

    let capabilities = Array.isArray(body.capabilities)
      ? body.capabilities.map(String)
      : preset
        ? [...preset.capabilities]
        : [];
    capabilities = [...new Set(capabilities)];
    if (!capabilities.length) {
      throw httpError(400, "Pick at least one capability, or a preset.");
    }
    for (const cap of capabilities) {
      if (!allowed.has(cap)) throw httpError(400, `Unknown capability ${cap}.`);
    }
    if (capabilities.includes("image_generation") === false) {
      /* FLUX is Phase E; the checkbox exists so a later preset can enable it. */
    }

    const maxTokens = Number(body.maxTokens ?? preset?.maxTokens ?? 512);
    const maxContext = Number(body.maxContext ?? preset?.maxContext ?? 4096);
    const forceNoStream = Boolean(body.forceNoStream ?? preset?.forceNoStream ?? false);
    const logPrompts = Boolean(body.logPrompts ?? preset?.logPrompts ?? false);
    const maxResponseBytes = Number(body.maxResponseBytes ?? preset?.maxResponseBytes ?? 1_048_576);
    const rpm = Number(body.rpm ?? 30);
    const name = String(body.name || "").trim();
    if (!name) throw httpError(400, "Key name is required.");

    const { publicId, secret, plaintext } = mintSecret();
    const secretHash = await hashSecret(secret);
    const origins = dashboardOrigin();
    const models = Array.isArray(body.models) ? body.models.map(String) : [];
    const tools = Array.isArray(body.tools) ? body.tools.map(String).slice(0, 12) : [];

    const inserted = await db`
      INSERT INTO api_keys (
        tenant_id, public_id, secret_hash, name, preset, capabilities, models, tools,
        max_tokens, max_context, rpm, log_prompts, force_no_stream, max_response_bytes,
        allowed_origins, salesforce_org_id
      ) VALUES (
        ${tenantId}::uuid,
        ${publicId},
        ${secretHash},
        ${name},
        ${presetName},
        ${JSON.stringify(capabilities)}::jsonb,
        ${JSON.stringify(models)}::jsonb,
        ${JSON.stringify(tools)}::jsonb,
        ${maxTokens},
        ${maxContext},
        ${rpm},
        ${logPrompts},
        ${forceNoStream},
        ${maxResponseBytes},
        ${JSON.stringify(origins)}::jsonb,
        ${body.salesforceOrgId ? String(body.salesforceOrgId) : null}
      )
      RETURNING id, tenant_id, public_id, name, preset, capabilities, models, max_tokens,
                max_context, rpm, force_no_stream, log_prompts, revoked_at, created_at
    `;
    return created(
      {
        key: publicKey(inserted[0]),
        plaintext,
        shownOnce: true,
        warning:
          "Store this key now. Cloudiator will not show it again. Revoking it takes up to 60 seconds to propagate (worker key cache).",
      },
      cookie,
    );
  }

  const revoke = path.match(/^\/keys\/([^/]+)\/revoke$/);
  if (revoke && method === "POST") {
    const keyId = revoke[1];
    const rows = await db`
      UPDATE api_keys SET revoked_at = now()
      WHERE id = ${keyId}::uuid AND revoked_at IS NULL
      RETURNING id, public_id, revoked_at
    `;
    if (!rows.length) throw httpError(404, "Key not found or already revoked.");
    return ok(
      {
        key: rows[0],
        warning:
          "Revocation takes up to 60 seconds to propagate (worker key cache). POST /v1/admin/cache/flush on the Mini makes it immediate.",
      },
      cookie,
    );
  }

  const usage = path.match(/^\/keys\/([^/]+)\/usage$/);
  if (usage && method === "GET") {
    const keyId = usage[1];
    await db`
      INSERT INTO usage_daily (day, key_id, tenant_id, route, calls, errors,
                               prompt_tokens, completion_tokens, bytes_out)
      SELECT date_trunc('day', ts)::date, key_id, tenant_id, route,
             count(*)::int, count(*) FILTER (WHERE status >= 400)::int,
             coalesce(sum(prompt_tokens), 0), coalesce(sum(completion_tokens), 0),
             coalesce(sum(bytes_out), 0)
      FROM usage_events
      WHERE key_id = ${keyId}::uuid AND ts >= date_trunc('day', now())
      GROUP BY 1, 2, 3, 4
      ON CONFLICT (day, key_id, route) DO UPDATE SET
        calls = EXCLUDED.calls,
        errors = EXCLUDED.errors,
        prompt_tokens = EXCLUDED.prompt_tokens,
        completion_tokens = EXCLUDED.completion_tokens,
        bytes_out = EXCLUDED.bytes_out
    `;
    const rows = await db`
      SELECT day, route, calls, errors, prompt_tokens, completion_tokens, bytes_out
      FROM usage_daily
      WHERE key_id = ${keyId}::uuid
      ORDER BY day ASC, route ASC
    `;
    return ok({ days: rows }, cookie);
  }

  const openapi = path.match(/^\/keys\/([^/]+)\/openapi$/);
  if (openapi && method === "GET") {
    const keyId = openapi[1];
    const target = (event.queryStringParameters?.target || "").trim() || null;
    if (target && target !== "salesforce") {
      throw httpError(400, "target must be omitted or salesforce.");
    }
    const rows = await db`
      SELECT capabilities FROM api_keys WHERE id = ${keyId}::uuid
    `;
    if (!rows.length) throw httpError(404, "Key not found.");
    const capabilities = asList(rows[0].capabilities);
    const doc = await buildOpenApi(capabilities, {
      target,
      publicBaseUrl: apiUrl,
      version: "0.1.0",
    });
    const filename =
      target === "salesforce" ? "cloudiator-salesforce.openapi.json" : "cloudiator.openapi.json";
    return {
      statusCode: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
        "Set-Cookie": cookie,
      },
      body: JSON.stringify(doc, null, 2),
    };
  }

  throw httpError(404, "Not found.");
}

export async function handler(event) {
  try {
    return await handle(event);
  } catch (err) {
    const status = err.statusCode || 500;
    const payload = err.payload || { error: err.message || "The dashboard failed to handle this request." };
    if (status >= 500) {
      console.error(err);
    }
    return json(status, payload);
  }
}
