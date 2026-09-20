/**
 * Cloudflare Access is the only authenticator. There is no login form, no
 * shared admin password, and no Netlify Identity (PLAN.md §12, Phase C).
 *
 * Production functions trust Cf-Access-Authenticated-User-Email and nothing
 * else. ADMIN_SESSION_SECRET signs the session cookie described in docs/env.md.
 * Direct hits on *.netlify.app can spoof that header — disable the Netlify
 * subdomain and serve only app.cloudiator.org behind Access.
 */
import { createHmac, timingSafeEqual } from "node:crypto";

import { httpError } from "./http.mjs";

const EMAIL_HEADER = "cf-access-authenticated-user-email";
const COOKIE_NAME = "cld_admin";
const COOKIE_MAX_AGE = 12 * 60 * 60;

function headersOf(event) {
  const out = {};
  for (const [key, value] of Object.entries(event.headers || {})) {
    out[key.toLowerCase()] = value;
  }
  return out;
}

export function requireAdminSecret() {
  const secret = process.env.ADMIN_SESSION_SECRET || "";
  if (secret.length < 16) {
    throw httpError(
      500,
      "ADMIN_SESSION_SECRET is not set. Put it in the Netlify site env (server functions only).",
    );
  }
  return secret;
}

export function accessEmail(event) {
  const headers = headersOf(event);
  const header = String(headers[EMAIL_HEADER] || "").trim();
  if (header) {
    if (!header.includes("@")) {
      throw httpError(401, "Cloudflare Access required.");
    }
    return header.toLowerCase();
  }
  if (process.env.NETLIFY_DEV === "true" && process.env.DEV_ACCESS_EMAIL) {
    return process.env.DEV_ACCESS_EMAIL.trim().toLowerCase();
  }
  throw httpError(
    401,
    "Cloudflare Access required. This app has no login form and no shared password.",
  );
}

export function signSession(email, secret) {
  const payload = Buffer.from(
    JSON.stringify({ email, exp: Date.now() + COOKIE_MAX_AGE * 1000 }),
  ).toString("base64url");
  const sig = createHmac("sha256", secret).update(payload).digest("base64url");
  return `${payload}.${sig}`;
}

export function sessionCookie(email, secret) {
  const value = signSession(email, secret);
  const secure = process.env.NETLIFY_DEV === "true" ? "" : "; Secure";
  return `${COOKIE_NAME}=${value}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${COOKIE_MAX_AGE}${secure}`;
}

export function verifySessionCookie(event, secret) {
  const headers = headersOf(event);
  const cookie = headers.cookie || "";
  const match = cookie.match(new RegExp(`(?:^|; )${COOKIE_NAME}=([^;]+)`));
  if (!match) return null;
  const [payload, sig] = match[1].split(".");
  if (!payload || !sig) return null;
  const expected = createHmac("sha256", secret).update(payload).digest("base64url");
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    if (!data.email || data.exp < Date.now()) return null;
    return String(data.email).toLowerCase();
  } catch {
    return null;
  }
}

export function identify(event) {
  const secret = requireAdminSecret();
  const email = accessEmail(event);
  return { email, secret, cookie: sessionCookie(email, secret) };
}
