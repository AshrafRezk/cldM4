#!/usr/bin/env node
/**
 * Build a Metadata API zip (package.xml at zip root) into:
 * - netlify/functions/_lib/sf-package/ (OAuth install deploy)
 * - public/salesforce/ (manual download)
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, copyFileSync, existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = join(here, "..");
const repoRoot = join(dashboardRoot, "../..");
const salesforceRoot = join(repoRoot, "salesforce");
const forceApp = join(salesforceRoot, "force-app/main/default");
const packageXml = join(salesforceRoot, "package.xml");

if (!existsSync(forceApp) || !existsSync(packageXml)) {
  console.warn("stage-sf-package: salesforce/force-app missing — skipping zip");
  process.exit(0);
}

const stage = join(dashboardRoot, ".sf-package-stage");
const outFn = join(dashboardRoot, "netlify/functions/_lib/sf-package");
const outPublic = join(dashboardRoot, "public/salesforce");
rmSync(stage, { recursive: true, force: true });
mkdirSync(stage, { recursive: true });
mkdirSync(outFn, { recursive: true });
mkdirSync(outPublic, { recursive: true });

copyFileSync(packageXml, join(stage, "package.xml"));
for (const name of [
  "applications",
  "classes",
  "lwc",
  "objects",
  "permissionsets",
  "remoteSiteSettings",
  "tabs",
]) {
  const src = join(forceApp, name);
  if (existsSync(src)) {
    spawnSync("cp", ["-a", src, join(stage, name)], { stdio: "inherit" });
  }
}

const zipPath = join(outFn, "cloudiator-unmanaged.zip");
rmSync(zipPath, { force: true });
const zipped = spawnSync("zip", ["-r", zipPath, "."], { cwd: stage, stdio: "inherit" });
if (zipped.status !== 0) {
  console.error("stage-sf-package: zip failed");
  process.exit(1);
}
copyFileSync(zipPath, join(outPublic, "cloudiator-unmanaged.zip"));
rmSync(stage, { recursive: true, force: true });
console.log("stage-sf-package:", zipPath);
