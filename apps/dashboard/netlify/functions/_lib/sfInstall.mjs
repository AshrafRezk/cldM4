/**
 * One-click Salesforce install.
 *
 * Salesforce performs login — no client secret on Netlify.
 *
 * 1) If a public 04t package id is configured → redirect to Salesforce’s installer.
 * 2) Else PKCE OAuth with a public Connected App consumer key → Metadata deploy
 *    the unmanaged zip, assign Cloudiator Admin, write minted API key into org config.
 */
import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Connection } from "jsforce";

import { accessEmail, requireAdminSecret } from "./access.mjs";
import { dashboardOrigin, publicApiUrl } from "./db.mjs";
import { httpError } from "./http.mjs";
import { publicInstallIds } from "./sfInstallPublic.mjs";

const STATE_COOKIE = "cld_sf_oauth";
const VERIFIER_COOKIE = "cld_sf_pkce";
const STATE_MAX_AGE = 15 * 60;
const ZIP_REL = "sf-package/cloudiator-unmanaged.zip";

function b64url(buf) {
  return Buffer.from(buf).toString("base64url");
}

function signState(payload, secret) {
  const body = b64url(JSON.stringify(payload));
  const sig = createHmac("sha256", secret).update(body).digest("base64url");
  return `${body}.${sig}`;
}

function verifyState(token, secret) {
  const [body, sig] = String(token || "").split(".");
  if (!body || !sig) throw httpError(400, "Invalid OAuth state.");
  const expect = createHmac("sha256", secret).update(body).digest("base64url");
  const a = Buffer.from(sig);
  const b = Buffer.from(expect);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    throw httpError(400, "Invalid OAuth state signature.");
  }
  const payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
  if (!payload.exp || Date.now() > payload.exp) {
    throw httpError(400, "OAuth state expired. Click Install again.");
  }
  return payload;
}

function cookieHeader(name, value, maxAge) {
  return [
    `${name}=${encodeURIComponent(value)}`,
    "Path=/",
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
    `Max-Age=${maxAge}`,
  ].join("; ");
}

function clearCookie(name) {
  return cookieHeader(name, "", 0);
}

function readCookie(event, name) {
  const headers = event.headers || {};
  const raw = headers.cookie || headers.Cookie || "";
  const match = String(raw)
    .split(";")
    .map((p) => p.trim())
    .find((p) => p.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : "";
}

function redirectUri() {
  return `${dashboardOrigin().replace(/\/$/, "")}/api/salesforce/oauth/callback`;
}

function loginHost(kind) {
  return kind === "test" || kind === "sandbox" ? "https://test.salesforce.com" : "https://login.salesforce.com";
}

function pkcePair() {
  const verifier = b64url(randomBytes(32));
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

export function salesforceInstallConfigured() {
  const ids = publicInstallIds();
  const packageId = ids.packageVersionId;
  return {
    packageInstallUrl: packageId
      ? `https://login.salesforce.com/packaging/installPackage.apexp?p0=${encodeURIComponent(packageId)}`
      : null,
    packageInstallUrlSandbox: packageId
      ? `https://test.salesforce.com/packaging/installPackage.apexp?p0=${encodeURIComponent(packageId)}`
      : null,
    oauthReady: Boolean(ids.oauthClientId),
    packageReady: Boolean(packageId),
    oneClick: Boolean(packageId || ids.oauthClientId),
    mode: packageId ? "package" : ids.oauthClientId ? "oauth_pkce" : "none",
    zipDownloadPath: "/salesforce/cloudiator-unmanaged.zip",
    needsPublicConfig: !packageId && !ids.oauthClientId,
  };
}

/**
 * GET (legacy) or POST { login, apiKey?, baseUrl? }
 * Returns redirect response (GET) or JSON { redirectUrl } (POST).
 */
export async function startSalesforceInstall(event) {
  accessEmail(event);
  const secret = requireAdminSecret();
  const cfg = salesforceInstallConfigured();
  const ids = publicInstallIds();
  const method = event.httpMethod || "GET";

  let login = "login";
  let apiKey = "";
  let baseUrl = publicApiUrl();
  let configureOnly = false;

  if (method === "POST") {
    const body = event.body
      ? JSON.parse(event.isBase64Encoded ? Buffer.from(event.body, "base64").toString("utf8") : event.body)
      : {};
    login = String(body.login || "login").toLowerCase();
    apiKey = String(body.apiKey || "").trim();
    configureOnly = Boolean(body.configureOnly);
    if (body.baseUrl) baseUrl = String(body.baseUrl).trim().replace(/\/$/, "");
  } else {
    const qs = event.queryStringParameters || {};
    login = String(qs.login || "login").toLowerCase();
  }

  if (apiKey && !/^sk-cld-[a-z0-9]+_[A-Za-z0-9_-]+$/.test(apiKey)) {
    throw httpError(400, "API key must look like sk-cld-{public_id}_{secret}.");
  }
  if (configureOnly && !apiKey) {
    throw httpError(400, "Paste an existing sk-cld-… key to connect it to the org.");
  }

  const host = loginHost(login);

  // Salesforce-native package installer — no OAuth client on Cloudiator.
  // Key wiring still needs PKCE configure; package URL alone cannot write the key.
  if (cfg.packageInstallUrl && !configureOnly && !apiKey) {
    const url = login === "test" || login === "sandbox" ? cfg.packageInstallUrlSandbox : cfg.packageInstallUrl;
    if (method === "POST") {
      return {
        statusCode: 200,
        headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
        body: JSON.stringify({ redirectUrl: url, mode: "package" }),
      };
    }
    return { statusCode: 302, headers: { Location: url, "Cache-Control": "no-store" }, body: "" };
  }

  if (!ids.oauthClientId) {
    throw httpError(
      503,
      "Set a public SF_PACKAGE_VERSION_ID (04t…) or SF_OAUTH_CLIENT_ID in apps/dashboard/netlify/functions/_lib/sfInstallConfig.json — no client secret. See docs/salesforce-app.md.",
    );
  }

  const { verifier, challenge } = pkcePair();
  const state = signState(
    {
      n: randomBytes(16).toString("hex"),
      email: accessEmail(event),
      login,
      apiKey: apiKey || undefined,
      baseUrl,
      configureOnly,
      exp: Date.now() + STATE_MAX_AGE * 1000,
    },
    secret,
  );

  const auth = new URL(`${host}/services/oauth2/authorize`);
  auth.searchParams.set("response_type", "code");
  auth.searchParams.set("client_id", ids.oauthClientId);
  auth.searchParams.set("redirect_uri", redirectUri());
  auth.searchParams.set("scope", "api refresh_token");
  auth.searchParams.set("state", state);
  auth.searchParams.set("code_challenge", challenge);
  auth.searchParams.set("code_challenge_method", "S256");
  auth.searchParams.set("prompt", "login consent");

  const headers = {
    "Set-Cookie": [cookieHeader(STATE_COOKIE, state, STATE_MAX_AGE), cookieHeader(VERIFIER_COOKIE, verifier, STATE_MAX_AGE)],
    "Cache-Control": "no-store",
  };

  if (method === "POST") {
    return {
      statusCode: 200,
      headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
      // Netlify merges Set-Cookie poorly as array — join via multi-value below
      multiValueHeaders: {
        "Set-Cookie": [
          cookieHeader(STATE_COOKIE, state, STATE_MAX_AGE),
          cookieHeader(VERIFIER_COOKIE, verifier, STATE_MAX_AGE),
        ],
      },
      body: JSON.stringify({ redirectUrl: auth.toString(), mode: "oauth_pkce" }),
    };
  }

  return {
    statusCode: 302,
    headers: { Location: auth.toString(), ...headers },
    multiValueHeaders: {
      "Set-Cookie": [
        cookieHeader(STATE_COOKIE, state, STATE_MAX_AGE),
        cookieHeader(VERIFIER_COOKIE, verifier, STATE_MAX_AGE),
      ],
    },
    body: "",
  };
}

function zipPath() {
  return join(dirname(fileURLToPath(import.meta.url)), ZIP_REL);
}

async function exchangeCode(host, code, verifier) {
  const ids = publicInstallIds();
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    client_id: ids.oauthClientId,
    redirect_uri: redirectUri(),
    code_verifier: verifier,
  });
  const res = await fetch(`${host}/services/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw httpError(502, json.error_description || json.error || "Salesforce token exchange failed.");
  }
  return json;
}

function deployZip(conn, buffer) {
  return new Promise((resolve, reject) => {
    conn.metadata
      .deploy(buffer, {
        singlePackage: true,
        rollbackOnError: true,
        purgeOnDelete: false,
        ignoreWarnings: false,
      })
      .complete((err, result) => {
        if (err) reject(err);
        else resolve(result);
      });
  });
}

async function assignAdminPermset(conn) {
  try {
    const ps = await conn.query(
      "SELECT Id FROM PermissionSet WHERE Name = 'Cloudiator_Admin' AND NamespacePrefix = null LIMIT 1",
    );
    const permissionSetId = ps.records?.[0]?.Id;
    if (!permissionSetId) return { assigned: false, reason: "permset_missing" };
    const identity = await conn.identity();
    const userId = identity.user_id;
    const existing = await conn.query(
      `SELECT Id FROM PermissionSetAssignment WHERE AssigneeId = '${userId}' AND PermissionSetId = '${permissionSetId}' LIMIT 1`,
    );
    if (existing.totalSize > 0) return { assigned: true, already: true };
    await conn.sobject("PermissionSetAssignment").create({
      AssigneeId: userId,
      PermissionSetId: permissionSetId,
    });
    return { assigned: true, already: false };
  } catch (err) {
    return { assigned: false, reason: String(err.message || err) };
  }
}

async function writeOrgConfig(conn, apiKey, baseUrl) {
  if (!apiKey) return { written: false, reason: "no_key" };
  try {
    const identity = await conn.identity();
    const orgId = identity.organization_id;
    const existing = await conn.query(
      `SELECT Id FROM Cloudiator_Config__c WHERE SetupOwnerId = '${orgId}' LIMIT 1`,
    );
    const fields = {
      Api_Key__c: apiKey,
      Base_URL__c: baseUrl || publicApiUrl(),
      Default_Model__c: process.env.DEFAULT_MODEL || "gemma4:e4b-it-qat",
      Use_Named_Credential__c: false,
    };
    if (existing.totalSize > 0) {
      await conn.sobject("Cloudiator_Config__c").update({ Id: existing.records[0].Id, ...fields });
    } else {
      await conn.sobject("Cloudiator_Config__c").create({ SetupOwnerId: orgId, ...fields });
    }
    return { written: true };
  } catch (err) {
    return { written: false, reason: String(err.message || err) };
  }
}

export async function completeSalesforceInstall(event) {
  const secret = requireAdminSecret();
  const qs = event.queryStringParameters || {};
  const origin = dashboardOrigin().replace(/\/$/, "");
  const clear = [
    clearCookie(STATE_COOKIE),
    clearCookie(VERIFIER_COOKIE),
  ];
  const fail = (message) => ({
    statusCode: 302,
    headers: {
      Location: `${origin}/console?tab=salesforce&sf_install=err&message=${encodeURIComponent(message).slice(0, 180)}`,
      "Cache-Control": "no-store",
    },
    multiValueHeaders: { "Set-Cookie": clear },
    body: "",
  });

  if (qs.error) {
    return fail(String(qs.error_description || qs.error));
  }

  const code = qs.code;
  const state = qs.state;
  if (!code || !state) return fail("Missing OAuth code/state.");

  let payload;
  try {
    payload = verifyState(state, secret);
  } catch (e) {
    return fail(e.message || "OAuth state invalid.");
  }

  const verifier = readCookie(event, VERIFIER_COOKIE);
  if (!verifier) return fail("Missing PKCE verifier cookie. Allow cookies and try Install again.");

  const host = loginHost(payload.login);
  let token;
  try {
    token = await exchangeCode(host, code, verifier);
  } catch (e) {
    return fail(e.message || "Token exchange failed.");
  }

  const conn = new Connection({
    instanceUrl: token.instance_url,
    accessToken: token.access_token,
    version: "62.0",
  });

  let components = 0;
  if (!payload.configureOnly) {
    const path = zipPath();
    if (!existsSync(path)) {
      return fail("Package zip missing on server. Rebuild the dashboard with stage-sf-package.");
    }
    let deployResult;
    try {
      deployResult = await deployZip(conn, readFileSync(path));
    } catch (e) {
      return fail(`Deploy failed: ${e.message || e}`);
    }
    if (!deployResult?.success) {
      const details = (deployResult?.details?.componentFailures || [])
        .slice(0, 3)
        .map((f) => f.problem || f.fullName)
        .join("; ");
      return fail(details || "Metadata deploy reported failure.");
    }
    components = deployResult.numberComponentsDeployed || 0;
  }

  const perm = await assignAdminPermset(conn);
  const cfgWrite = await writeOrgConfig(conn, payload.apiKey, payload.baseUrl);
  if (payload.configureOnly && !cfgWrite.written) {
    return fail(cfgWrite.reason || "Could not write API key into org Cloudiator Setup.");
  }
  const q = new URLSearchParams({
    tab: "salesforce",
    sf_install: "ok",
    components: String(components),
    permset: perm.assigned ? "1" : "0",
    key: cfgWrite.written ? "1" : "0",
    mode: payload.configureOnly ? "connect" : "install",
  });
  return {
    statusCode: 302,
    headers: {
      Location: `${origin}/console?${q}`,
      "Cache-Control": "no-store",
    },
    multiValueHeaders: { "Set-Cookie": clear },
    body: "",
  };
}
