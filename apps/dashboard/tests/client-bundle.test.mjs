import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = join(here, "../src");

test("the Vite client does not import Neon or DATABASE_URL", () => {
  const files = ["App.jsx", "api.js", "Playground.jsx", "KeyForm.jsx", "main.jsx"];
  for (const name of files) {
    const src = readFileSync(join(srcDir, name), "utf8");
    assert.equal(src.includes("neon.tech"), false, name);
    assert.equal(src.includes("DATABASE_URL"), false, name);
    assert.equal(src.includes("@neondatabase/serverless"), false, name);
  }
});

test("the app has no login form and no Netlify Identity", () => {
  const app = readFileSync(join(srcDir, "App.jsx"), "utf8");
  assert.match(app, /Cloudflare Access required/);
  assert.equal(/type=["']password["']/.test(app), false);
  assert.equal(app.includes("netlifyIdentity"), false);
  assert.equal(app.includes("shared password") || app.includes("no shared password"), true);
});
