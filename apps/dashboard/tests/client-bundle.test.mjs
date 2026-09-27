import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = join(here, "../src");

function sourceFiles() {
  return readdirSync(srcDir).filter((name) => /\.(jsx|js|css)$/.test(name));
}

test("the Vite client does not import Neon or DATABASE_URL", () => {
  for (const name of sourceFiles()) {
    const src = readFileSync(join(srcDir, name), "utf8");
    assert.equal(src.includes("neon.tech"), false, name);
    assert.equal(src.includes("DATABASE_URL"), false, name);
    assert.equal(src.includes("@neondatabase/serverless"), false, name);
  }
});

test("the app has no login form and no Netlify Identity", () => {
  const app = ["App.jsx", "Console.jsx", "Landing.jsx"]
    .map((name) => readFileSync(join(srcDir, name), "utf8"))
    .join("\n");
  assert.match(app, /Cloudflare Access required/);
  assert.equal(/type=["']password["']/.test(app), false);
  assert.equal(app.includes("netlifyIdentity"), false);
  assert.equal(app.includes("shared password") || app.includes("no shared password"), true);
});

test("the landing page positions Cloudiator as Agentforce-native private AI", () => {
  const landing = readFileSync(join(srcDir, "Landing.jsx"), "utf8");
  assert.match(landing, /Agentforce/);
  assert.match(landing, /Private AI/);
  assert.equal(landing.includes("fetch("), false);
});
