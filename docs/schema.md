# Neon / Postgres schema

Apply in the Neon SQL editor during Phase B. Names are stable; do not rename in later phases.

Use the **pooled** connection string (`-pooler` in the hostname) and the pool settings in `docs/env.md`. The Mini is one long-lived process against a compute that auto-suspends when idle.

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
  secret_hash     text NOT NULL,                  -- argon2id: t=2, m=65536, p=1, len=32, salt=16
  name            text NOT NULL,
  preset          text,
  capabilities    jsonb NOT NULL DEFAULT '[]',    -- ["chat","embeddings","tools.ocr",...]
  models          jsonb NOT NULL DEFAULT '[]',    -- empty = default model only; never lists an unpulled model
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
  max_response_bytes int NOT NULL DEFAULT 1048576, -- Apex heap is ~6MB; cap the body
  revoked_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX api_keys_public_id_idx ON api_keys (public_id) WHERE revoked_at IS NULL;

CREATE TABLE usage_events (
  id            bigserial PRIMARY KEY,
  key_id        uuid REFERENCES api_keys(id) ON DELETE SET NULL,
  tenant_id     uuid REFERENCES tenants(id) ON DELETE SET NULL,
  ts            timestamptz NOT NULL DEFAULT now(),
  request_id    text,           -- matches the X-Request-Id response header
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
CREATE INDEX usage_events_ts_idx     ON usage_events (ts);

-- Dashboard reads this, not the raw events table.
CREATE TABLE usage_daily (
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

CREATE TABLE jobs (
  id            uuid PRIMARY KEY,
  key_id        uuid REFERENCES api_keys(id) ON DELETE SET NULL,
  status        text NOT NULL,  -- queued|running|succeeded|failed
  kind          text NOT NULL,  -- image|chat_heavy|transcribe|tool
  request       jsonb NOT NULL,
  result        jsonb,
  error         text,
  idempotency_key text,
  request_id    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- An Apex retry of a timed-out callout must return the original job, not start a second FLUX run.
CREATE UNIQUE INDEX jobs_idempotency_idx
  ON jobs (key_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

-- Mini SQLite mirrors jobs for crash safety; the Neon copy is for the dashboard.
```

## Retention — not optional on a free tier

Every request writes a `usage_events` row. At a few thousand calls a day, keeping raw rows forever fills a free-tier Neon project, and when storage runs out **key minting starts failing too** — the outage is not limited to analytics.

Roll up nightly, then delete:

```sql
INSERT INTO usage_daily (day, key_id, tenant_id, route, calls, errors,
                         prompt_tokens, completion_tokens, bytes_out)
SELECT date_trunc('day', ts)::date, key_id, tenant_id, route,
       count(*), count(*) FILTER (WHERE status >= 400),
       coalesce(sum(prompt_tokens), 0), coalesce(sum(completion_tokens), 0),
       coalesce(sum(bytes_out), 0)
FROM usage_events
WHERE ts < date_trunc('day', now())
GROUP BY 1, 2, 3, 4
ON CONFLICT (day, key_id, route) DO UPDATE SET
  calls             = EXCLUDED.calls,
  errors            = EXCLUDED.errors,
  prompt_tokens     = EXCLUDED.prompt_tokens,
  completion_tokens = EXCLUDED.completion_tokens,
  bytes_out         = EXCLUDED.bytes_out;

DELETE FROM usage_events WHERE ts < now() - interval '30 days';
```

Schedule it (Neon scheduled job, a cron on the Mini, or a Netlify scheduled function) and tick it off in `docs/operator-checklist.md` §3.

## Mini-local SQLite (`QUEUE_DB`)

Not in Neon. Lives at `~/Cloudiator/queue.db` on the Mini and exists so a Neon blip never costs a job or fails a request.

```sql
-- jobs queue: survives a worker restart
CREATE TABLE IF NOT EXISTS job_queue (
  id              TEXT PRIMARY KEY,
  key_id          TEXT,
  kind            TEXT NOT NULL,
  status          TEXT NOT NULL,
  request_json    TEXT NOT NULL,
  result_json     TEXT,
  error           TEXT,
  idempotency_key TEXT,
  request_id      TEXT,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS job_queue_idem_idx
  ON job_queue (key_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- usage outbox: written on the request path (local, cheap), flushed to Neon in the background
CREATE TABLE IF NOT EXISTS usage_outbox (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  payload     TEXT NOT NULL,        -- one usage_events row as JSON
  created_at  INTEGER NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0
);
```

Outbox rules (`PLAN.md` §11):

- Flush every 10s in batches of 500.
- Cap at 100k rows; drop oldest first and log the drop. Metrics matter less than the appliance staying up.
- Never block or fail a request on a usage write.
- Expose the depth as `outbox_depth` in `/v1/health`. A depth that only grows means Neon has been unreachable for a while.

`queue.db` deliberately has no backup story: a corrupt file loses in-flight jobs, not keys and not billing-relevant history. Delete it, restart, move on.

## Key format

Plaintext: `sk-cld-{public_id}_{secret}`

`public_id` is 8+ urlsafe chars and is what you look up by (indexed). `secret` is 32+ random bytes and exists only as an argon2id hash at rest. Verify in constant time, and cache the verification for 60s so argon2id's 64 MiB cost stays off the hot path — which also means **revocation takes up to 60 seconds**, and the dashboard must say so.
