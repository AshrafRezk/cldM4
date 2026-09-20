#!/usr/bin/env node
/**
 * Fail the build if the client bundle contains the Neon hostname.
 * DATABASE_URL belongs in Netlify function env, never in dist/ (PLAN.md §13).
 */
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, "..", "dist");

if (!existsSync(dist)) {
  console.error("dist/ is missing. Run npm run build first.");
  process.exit(2);
}

let found = "";
try {
  found = execFileSync("grep", ["-r", "neon.tech", dist], { encoding: "utf8" });
} catch (err) {
  if (err.status === 1) {
    console.log("check:no-neon: dist/ does not contain neon.tech");
    process.exit(0);
  }
  console.error(err.stderr || err.message);
  process.exit(err.status || 1);
}

console.error("DATABASE_URL leaked into the browser bundle:\n" + found);
process.exit(1);
