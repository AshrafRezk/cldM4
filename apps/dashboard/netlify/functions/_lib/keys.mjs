/**
 * Mint sk-cld-{public_id}_{secret} with the same argon2id parameters as the
 * worker (PLAN.md §12). The plaintext is returned once; Neon stores the hash.
 */
import { randomBytes } from "node:crypto";

import { argon2id } from "hash-wasm";

export const KEY_PREFIX = "sk-cld-";
export const PUBLIC_ID_ALPHABET = "abcdefghijkmnopqrstuvwxyz23456789";
export const PUBLIC_ID_LENGTH = 12;
export const SECRET_BYTES = 32;
export const ARGON2_TIME_COST = 2;
export const ARGON2_MEMORY_COST = 65536;
export const ARGON2_PARALLELISM = 1;
export const ARGON2_HASH_LEN = 32;
export const ARGON2_SALT_LEN = 16;

export function mintSecret() {
  const idBytes = randomBytes(PUBLIC_ID_LENGTH);
  let publicId = "";
  for (let i = 0; i < PUBLIC_ID_LENGTH; i += 1) {
    publicId += PUBLIC_ID_ALPHABET[idBytes[i] % PUBLIC_ID_ALPHABET.length];
  }
  const secret = randomBytes(SECRET_BYTES).toString("base64url");
  return { publicId, secret, plaintext: `${KEY_PREFIX}${publicId}_${secret}` };
}

export async function hashSecret(secret) {
  const salt = randomBytes(ARGON2_SALT_LEN);
  return argon2id({
    password: secret,
    salt,
    parallelism: ARGON2_PARALLELISM,
    iterations: ARGON2_TIME_COST,
    memorySize: ARGON2_MEMORY_COST,
    hashLength: ARGON2_HASH_LEN,
    outputType: "encoded",
  });
}

export function parsePreset(scopes, name) {
  const presets = scopes.presets || {};
  if (!name) return null;
  const spec = presets[name];
  if (!spec) return null;
  return {
    name,
    capabilities: [...(spec.capabilities || [])],
    maxTokens: spec.max_tokens ?? 512,
    maxContext: spec.max_context ?? 4096,
    forceNoStream: Boolean(spec.force_no_stream),
    logPrompts: Boolean(spec.log_prompts),
    maxResponseBytes: spec.max_response_bytes ?? 1_048_576,
  };
}
