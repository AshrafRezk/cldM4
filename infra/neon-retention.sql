-- Nightly (or daily) on Neon. Raw usage_events older than 30 days fill a free tier
-- and then key minting fails too. Tick operator-checklist §3 after scheduling.

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
