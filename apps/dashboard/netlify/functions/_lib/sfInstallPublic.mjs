import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function loadCfg() {
  const names = ["sfInstallConfig.json"];
  const dirs = [];
  try {
    if (import.meta?.url) dirs.push(dirname(fileURLToPath(import.meta.url)));
  } catch {
    /* CJS bundle empties import.meta */
  }
  dirs.push(
    join(process.cwd(), "netlify/functions/_lib"),
    process.cwd(),
  );
  for (const dir of dirs) {
    for (const name of names) {
      const path = join(dir, name);
      if (!existsSync(path)) continue;
      try {
        return JSON.parse(readFileSync(path, "utf8"));
      } catch {
        /* try next */
      }
    }
  }
  return {};
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
