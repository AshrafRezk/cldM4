import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function loadCfg() {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    return JSON.parse(readFileSync(join(here, "sfInstallConfig.json"), "utf8"));
  } catch {
    return {};
  }
}

const cfg = loadCfg();

export function publicInstallIds() {
  return {
    packageVersionId:
      (process.env.SF_PACKAGE_VERSION_ID || "").trim() || String(cfg.SF_PACKAGE_VERSION_ID || "").trim(),
    oauthClientId:
      (process.env.SF_OAUTH_CLIENT_ID || "").trim() || String(cfg.SF_OAUTH_CLIENT_ID || "").trim(),
  };
}
