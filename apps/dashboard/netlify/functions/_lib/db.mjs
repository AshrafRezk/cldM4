import { neon } from "@neondatabase/serverless";

import { httpError } from "./http.mjs";

let cached;

export function sql() {
  const url = process.env.DATABASE_URL || "";
  if (!url) {
    throw httpError(
      500,
      "DATABASE_URL is not set. Put the pooled Neon URL in the Netlify site env (server functions only).",
    );
  }
  if (!url.includes("-pooler")) {
    throw httpError(
      500,
      "DATABASE_URL must be the pooled Neon endpoint (-pooler in the host).",
    );
  }
  if (url.includes("neon.tech") === false) {
    // Still Neon-compatible hosts exist; the leak check is the browser bundle.
  }
  if (!cached) cached = neon(url);
  return cached;
}

export function publicApiUrl() {
  const url = (process.env.PUBLIC_API_URL || "https://api.cloudiator.org").replace(/\/$/, "");
  return url;
}

export function dashboardOrigin() {
  const fromEnv = (process.env.URL || process.env.DEPLOY_PRIME_URL || "").replace(/\/$/, "");
  const api = publicApiUrl();
  let derived = "https://app.cloudiator.org";
  try {
    const host = new URL(api).host;
    if (host.startsWith("api.")) derived = `${new URL(api).protocol}//app.${host.slice(4)}`;
  } catch {
    /* keep default */
  }
  const origins = new Set([derived, "https://app.cloudiator.org"]);
  if (fromEnv) origins.add(fromEnv);
  return [...origins];
}
