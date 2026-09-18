# Neon / Postgres schema

Apply in Neon SQL editor during Phase B. Names are stable; do not rename in later phases.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          text NOT NULL UNIQUE,
  name          text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  public_id       text NOT NULL UNIQUE,           -- the visible prefix after sk-cld-
  secret_hash     text NOT NULL,                  -- argon2id
  name            text NOT NULL,
  preset          text,
  capabilities    jsonb NOT NULL DEFAULT '[]',    -- ["chat","embeddings","tools.ocr",...]
  models          jsonb NOT NULL DEFAULT '["qwen3.5:9b"]',
  tools           jsonb NOT NULL DEFAULT '[]',    -- chat tool names, max 12
  max_tokens      int NOT NULL DEFAULT 512,
  max_context     int NOT NULL DEFAULT 4096,
  rpm             int NOT NULL DEFAULT 30,
  daily_token_budget int,
  allowed_origins jsonb NOT NULL DEFAULT '[]',
  salesforce_org_id text,
  log_prompts     boolean NOT NULL DEFAULT false,
  strip_exif      boolean NOT NULL DEFAULT true,
  force_no_stream boolean NOT NULL DEFAULT false, -- true for Salesforce preset
  revoked_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX api_keys_public_id_idx ON api_keys (public_id) WHERE revoked_at IS NULL;

CREATE TABLE usage_events (
  id            bigserial PRIMARY KEY,
  key_id        uuid REFERENCES api_keys(id) ON DELETE SET NULL,
  tenant_id     uuid REFERENCES tenants(id) ON DELETE SET NULL,
  ts            timestamptz NOT NULL DEFAULT now(),
  route         text NOT NULL,
  model         text,
  tool          text,
  status        int NOT NULL,
  latency_ms    int,
  prompt_tokens int,
  completion_tokens int,
  bytes_out     int,
  job_id        uuid,
  error_code    text
);

CREATE INDEX usage_events_key_ts_idx ON usage_events (key_id, ts DESC);

CREATE TABLE jobs (
  id            uuid PRIMARY KEY,
  key_id        uuid REFERENCES api_keys(id) ON DELETE SET NULL,
  status        text NOT NULL,  -- queued|running|succeeded|failed
  kind          text NOT NULL,  -- image|chat_heavy|transcribe|tool
  request       jsonb NOT NULL,
  result        jsonb,
  error         text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Mini SQLite mirrors jobs for crash safety; Neon copy is for the dashboard.
```

Key plaintext format: `sk-cld-{public_id}_{secret}`  
`public_id` is 8+ urlsafe chars used for lookup. `secret` is 32+ random bytes, only hashed at rest.
