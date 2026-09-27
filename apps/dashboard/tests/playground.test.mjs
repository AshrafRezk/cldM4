import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildRequest,
  describeRequest,
  summarize,
} from "../src/playgroundServices.js";

const chatFields = {
  model: "gemma4:e4b-it-qat",
  system: "Answer in Arabic.",
  prompt: "اكتب جملة واحدة بالفصحى عن الطقس.",
  maxTokens: "512",
  temperature: "0.2",
  jsonObject: true,
};

test("chat requests stay non-streaming and carry the form fields", () => {
  const built = buildRequest("chat", chatFields);
  assert.equal(built.method, "POST");
  assert.equal(built.path, "/v1/chat/completions");
  assert.equal(built.body.stream, false);
  assert.equal(built.body.max_tokens, 512);
  assert.equal(built.body.temperature, 0.2);
  assert.deepEqual(built.body.response_format, { type: "json_object" });
  assert.deepEqual(
    built.body.messages.map((message) => message.role),
    ["system", "user"],
  );
});

test("raw JSON replaces the chat form so tools and extra turns can be sent", () => {
  const raw = JSON.stringify({
    model: "gemma4:e4b-it-qat",
    stream: false,
    messages: [
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello" },
      { role: "user", content: "again" },
    ],
    tools: [{ type: "function", function: { name: "lookup" } }],
  });
  const built = buildRequest("chat", { ...chatFields, prompt: "" }, { rawBody: raw });
  assert.equal(built.body.messages.length, 3);
  assert.equal(built.body.tools[0].function.name, "lookup");
});

test("embeddings send one line as a string and several lines as an array", () => {
  const one = buildRequest("embeddings", { embedModel: "nomic-embed-text", embedInput: "cairo" });
  assert.equal(one.path, "/v1/embeddings");
  assert.equal(one.body.input, "cairo");
  const many = buildRequest("embeddings", {
    embedModel: "nomic-embed-text",
    embedInput: "cairo\nriyadh\n",
  });
  assert.deepEqual(many.body.input, ["cairo", "riyadh"]);
});

test("openapi can target the Salesforce subset", () => {
  assert.equal(describeRequest("openapi", { openapiTarget: "" }).path, "/v1/openapi.json");
  const built = buildRequest("openapi", { openapiTarget: "salesforce" });
  assert.equal(built.path, "/v1/openapi.json?target=salesforce");
});

test("custom requests stay on /v1 and health does not require a key", () => {
  assert.throws(() => buildRequest("custom", { customMethod: "GET", customPath: "https://evil.example/v1/models" }));
  assert.throws(() => buildRequest("custom", { customMethod: "GET", customPath: "/v1/../.env" }));
  const health = buildRequest("custom", { customMethod: "GET", customPath: "/v1/health" });
  assert.equal(health.requiresKey, false);
  assert.equal(health.body, null);
  const embeddings = buildRequest("custom", {
    customMethod: "POST",
    customPath: "/v1/embeddings",
    customBody: '{"model":"nomic-embed-text","input":"hi"}',
  });
  assert.equal(embeddings.requiresKey, true);
  assert.equal(embeddings.body.input, "hi");
});

test("embedding replies are summarized instead of dumping the full vector", () => {
  const view = summarize("embeddings", {
    object: "list",
    model: "nomic-embed-text",
    data: [{ object: "embedding", index: 0, embedding: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9] }],
  });
  assert.match(view.lead, /9 dimensions/);
  assert.equal(JSON.parse(view.jsonText).data[0].embedding.dimensions, 9);
  assert.equal(JSON.parse(view.jsonText).data[0].embedding.preview.length, 8);
});
