/**
 * One-click Salesforce unmanaged package install via OAuth + Metadata API.
 * Requires Netlify env: SF_OAUTH_CLIENT_ID, SF_OAUTH_CLIENT_SECRET (Connected App).
 * Optional: SF_PACKAGE_VERSION_ID (04t…) for native install URL instead of Metadata deploy.
 */
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Connection } from "jsforce";

import { accessEmail, requireAdminSecret } from "./access.mjs";
import { dashboardOrigin } from "./db.mjs";
import { httpError } from "./http.mjs";

const STATE_COOKIE = "cld_sf_oauth";
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

function cookieHeader(value, maxAge) {
  const parts = [
    `${STATE_COOKIE}=${value}`,
    "Path=/",
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
    `Max-Age=${maxAge}`,
  ];
  return parts.join("; ");
}

function clearCookie() {
  return cookieHeader("", 0);
}

export function salesforceInstallConfigured() {
  const packageId = (process.env.SF_PACKAGE_VERSION_ID || "").trim();
  const clientId = (process.env.SF_OAUTH_CLIENT_ID || "").trim();
  const clientSecret = (process.env.SF_OAUTH_CLIENT_SECRET || "").trim();
  return {
    packageInstallUrl: packageId
      ? `https://login.salesforce.com/packaging/installPackage.apexp?p0=${encodeURIComponent(packageId)}`
      : null,
    packageInstallUrlSandbox: packageId
      ? `https://test.salesforce.com/packaging/installPackage.apexp?p0=${encodeURIComponent(packageId)}`
      : null,
    oauthReady: Boolean(clientId && clientSecret),
    zipDownloadPath: "/salesforce/cloudiator-unmanaged.zip",
  };
}

function redirectUri() {
  const origin = dashboardOrigin().replace(/\/$/, "");
  return `${origin}/api/salesforce/oauth/callback`;
}

function loginHost(kind) {
  return kind === "test" || kind === "sandbox" ? "https://test.salesforce.com" : "https://login.salesforce.com";
}

export function startSalesforceInstall(event) {
  accessEmail(event);
  const secret = requireAdminSecret();
  const cfg = salesforceInstallConfigured();
  const qs = event.queryStringParameters || {};
  const login = String(qs.login || "login").toLowerCase();
  const host = loginHost(login);

  // Prefer official package installer when a 04t id is configured.
  if (cfg.packageInstallUrl) {
    const url = login === "test" || login === "sandbox" ? cfg.packageInstallUrlSandbox : cfg.packageInstallUrl;
    return {
      statusCode: 302,
      headers: { Location: url, "Cache-Control": "no-store" },
      body: "",
    };
  }

  if (!cfg.oauthReady) {
    throw httpError(
      503,
      "Salesforce install is not configured. Set SF_OAUTH_CLIENT_ID + SF_OAUTH_CLIENT_SECRET (Connected App), or SF_PACKAGE_VERSION_ID, in Netlify env.",
    );
  }

  const state = signState(
    {
      n: randomBytes(16).toString("hex"),
      email: accessEmail(event),
      login,
      exp: Date.now() + STATE_MAX_AGE * 1000,
    },
    secret,
  );

  const auth = new URL(`${host}/services/oauth2/authorize`);
  auth.searchParams.set("response_type", "code");
  auth.searchParams.set("client_id", process.env.SF_OAUTH_CLIENT_ID.trim());
  auth.searchParams.set("redirect_uri", redirectUri());
  auth.searchParams.set("scope", "api refresh_token");
  auth.searchParams.set("state", state);
  auth.searchParams.set("prompt", "login consent");

  return {
    statusCode: 302,
    headers: {
      Location: auth.toString(),
      "Set-Cookie": cookieHeader(state, STATE_MAX_AGE),
      "Cache-Control": "no-store",
    },
    body: "",
  };
}

function zipPath() {
  const here = dirname(fileURLToPath(import.meta.url));
  return join(here, ZIP_REL);
}

async function exchangeCode(host, code) {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    client_id: process.env.SF_OAUTH_CLIENT_ID.trim(),
    client_secret: process.env.SF_OAUTH_CLIENT_SECRET.trim(),
    redirect_uri: redirectUri(),
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
    const userId = conn.userInfo?.id || (await conn.identity()).user_id;
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

export async function completeSalesforceInstall(event) {
  const secret = requireAdminSecret();
  const qs = event.queryStringParameters || {};
  const err = qs.error;
  const origin = dashboardOrigin().replace(/\/$/, "");
  const fail = (message) => ({
    statusCode: 302,
    headers: {
      Location: `${origin}/console?tab=salesforce&sf_install=err&message=${encodeURIComponent(message).slice(0, 180)}`,
      "Set-Cookie": clearCookie(),
      "Cache-Control": "no-store",
    },
    body: "",
  });

  if (err) {
    return fail(String(qs.error_description || err));
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

  const host = loginHost(payload.login);
  let token;
  try {
    token = await exchangeCode(host, code);
  } catch (e) {
    return fail(e.message || "Token exchange failed.");
  }

  const path = zipPath();
  if (!existsSync(path)) {
    return fail("Package zip missing on server. Rebuild the dashboard with stage-sf-package.");
  }
  const zip = readFileSync(path);

  const conn = new Connection({
    instanceUrl: token.instance_url,
    accessToken: token.access_token,
    version: "62.0",
  });

  let deployResult;
  try {
    deployResult = await deployZip(conn, zip);
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

  const perm = await assignAdminPermset(conn);
  const components = deployResult.numberComponentsDeployed || 0;
  const q = new URLSearchParams({
    tab: "salesforce",
    sf_install: "ok",
    components: String(components),
    permset: perm.assigned ? "1" : "0",
  });
  return {
    statusCode: 302,
    headers: {
      Location: `${origin}/console?${q}`,
      "Set-Cookie": clearCookie(),
      "Cache-Control": "no-store",
    },
    body: "",
  };
}
