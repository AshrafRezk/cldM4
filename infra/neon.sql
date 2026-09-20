-- Cloudiator Neon schema. Apply once in the Neon SQL editor during Phase B.
-- Names are stable; do not rename in later phases.
-- Use the pooled connection string (-pooler in the hostname).
-- Retention job is infra/neon-retention.sql — do not skip it on a free tier.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          text NOT NULL UNIQUE,
  name          text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_keys (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  public_id       text NOT NULL UNIQUE,
  secret_hash     text NOT NULL,
  name            text NOT NULL,
  preset          text,
  capabilities    jsonb NOT NULL DEFAULT '[]',
  models          jsonb NOT NULL DEFAULT '[]',
  tools           jsonb NOT NULL DEFAULT '[]',
  max_tokens      int NOT NULL DEFAULT 512,
  max_context     int NOT NULL DEFAULT 4096,
  rpm             int NOT NULL DEFAULT 30,
  daily_token_budget int,
  allowed_origins jsonb NOT NULL DEFAULT '[]',
  salesforce_org_id text,
  log_prompts     boolean NOT NULL DEFAULT false,
  strip_exif      boolean NOT NULL DEFAULT true,
  force_no_stream boolean NOT NULL DEFAULT false,
  max_response_bytes int NOT NULL DEFAULT 1048576,
  revoked_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS api_keys_public_id_idx
  ON api_keys (public_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS usage_events (
  id            bigserial PRIMARY KEY,
  key_id        uuid REFERENCES api_keys(id) ON DELETE SET NULL,
  tenant_id     uuid REFERENCES tenants(id) ON DELETE SET NULL,
  ts            timestamptz NOT NULL DEFAULT now(),
  request_id    text,
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

CREATE INDEX IF NOT EXISTS usage_events_key_ts_idx ON usage_events (key_id, ts DESC);
CREATE INDEX IF NOT EXISTS usage_events_ts_idx     ON usage_events (ts);

CREATE TABLE IF NOT EXISTS usage_daily (
  day               date NOT NULL,
  key_id            uuid REFERENCES api_keys(id) ON DELETE CASCADE,
  tenant_id         uuid REFERENCES tenants(id) ON DELETE CASCADE,
  route             text NOT NULL,
  calls             int  NOT NULL DEFAULT 0,
  errors            int  NOT NULL DEFAULT 0,
  prompt_tokens     bigint NOT NULL DEFAULT 0,
  completion_tokens bigint NOT NULL DEFAULT 0,
  bytes_out         bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (day, key_id, route)
);

CREATE TABLE IF NOT EXISTS jobs (
  id            uuid PRIMARY KEY,
  key_id        uuid REFERENCES api_keys(id) ON DELETE SET NULL,
  status        text NOT NULL,
  kind          text NOT NULL,
  request       jsonb NOT NULL,
  result        jsonb,
  error         text,
  idempotency_key text,
  request_id    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency_idx
  ON jobs (key_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
