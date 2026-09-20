-- Mini-local SQLite at QUEUE_DB (~/Cloudiator/queue.db). Not Neon.
-- Jobs survive a FastAPI restart; usage_outbox survives a Neon blip.
-- No backup story: delete a corrupt file and restart.

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

CREATE TABLE IF NOT EXISTS usage_outbox (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  payload     TEXT NOT NULL,
  created_at  INTEGER NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0
);
