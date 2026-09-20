import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { KeyForm } from "./KeyForm.jsx";
import { Playground } from "./Playground.jsx";
import { SalesforcePanel } from "./SalesforcePanel.jsx";
import { UsageChart } from "./UsageChart.jsx";

export default function App() {
  const [me, setMe] = useState(null);
  const [scopes, setScopes] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState("");
  const [keys, setKeys] = useState([]);
  const [selectedKeyId, setSelectedKeyId] = useState("");
  const [plaintext, setPlaintext] = useState("");
  const [usage, setUsage] = useState([]);
  const [error, setError] = useState("");
  const [accessBlocked, setAccessBlocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tenantSlug, setTenantSlug] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [copied, setCopied] = useState(false);

  const selectedKey = keys.find((key) => key.id === selectedKeyId) || null;

  const load = useCallback(async () => {
    setError("");
    try {
      const [meBody, scopeBody, tenantBody] = await Promise.all([
        api.me(),
        api.scopes(),
        api.tenants(),
      ]);
      setMe(meBody);
      setScopes(scopeBody);
      setTenants(tenantBody.tenants || []);
      setAccessBlocked(false);
      if (!tenantId && tenantBody.tenants?.length) {
        setTenantId(tenantBody.tenants[0].id);
      }
    } catch (err) {
      if (err.status === 401) {
        setAccessBlocked(true);
        setError(err.message);
        return;
      }
      setError(err.message);
    }
  }, [tenantId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!tenantId) {
      setKeys([]);
      return;
    }
    api
      .keys(tenantId)
      .then((body) => {
        setKeys(body.keys || []);
        if (body.keys?.length && !selectedKeyId) setSelectedKeyId(body.keys[0].id);
      })
      .catch((err) => setError(err.message));
  }, [tenantId, selectedKeyId]);

  const refreshUsage = useCallback(async (keyId) => {
    if (!keyId) {
      setUsage([]);
      return;
    }
    const body = await api.usage(keyId);
    setUsage(body.days || []);
  }, []);

  useEffect(() => {
    refreshUsage(selectedKeyId).catch((err) => setError(err.message));
  }, [selectedKeyId, refreshUsage]);

  async function createTenant(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = await api.createTenant({ slug: tenantSlug, name: tenantName || tenantSlug });
      setTenants((current) => [body.tenant, ...current.filter((row) => row.id !== body.tenant.id)]);
      setTenantId(body.tenant.id);
      setTenantSlug("");
      setTenantName("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onMinted(result) {
    setPlaintext(result.plaintext);
    setKeys((current) => [result.key, ...current]);
    setSelectedKeyId(result.key.id);
    setCopied(false);
  }

  async function revoke() {
    if (!selectedKey || selectedKey.revokedAt) return;
    if (!window.confirm(`Revoke ${selectedKey.publicId}? Chat with this key will fail after the cache TTL.`)) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = await api.revokeKey(selectedKey.id);
      setKeys((current) =>
        current.map((key) => (key.id === selectedKey.id ? { ...key, revokedAt: body.key.revoked_at } : key)),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const playgroundKey = plaintext || "";

  const chartDays = useMemo(() => {
    const byDay = new Map();
    for (const row of usage) {
      const day = String(row.day).slice(0, 10);
      const current = byDay.get(day) || { day, calls: 0, errors: 0, tokens: 0 };
      current.calls += Number(row.calls || 0);
      current.errors += Number(row.errors || 0);
      current.tokens += Number(row.prompt_tokens || 0) + Number(row.completion_tokens || 0);
      byDay.set(day, current);
    }
    return [...byDay.values()];
  }, [usage]);

  if (accessBlocked) {
    return (
      <main className="shell">
        <header className="top">
          <h1>Cloudiator</h1>
        </header>
        <section className="card">
          <h2>Cloudflare Access required</h2>
          <p>
            This dashboard has no login form and no shared password. Open{" "}
            <code>https://app.cloudiator.org</code> in a browser that can complete Cloudflare Access.
            An incognito window should be challenged by Access, not by this app.
          </p>
          {error ? <p className="error">{error}</p> : null}
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="top">
        <div>
          <h1>Cloudiator</h1>
          <p className="muted">
            Keys and usage in Neon. Inference stays on the Mini at {me?.apiUrl || "https://api.cloudiator.org"}.
          </p>
        </div>
        <div className="who">{me?.email}</div>
      </header>

      {error ? <p className="error">{error}</p> : null}

      <section className="grid">
        <div className="card">
          <h2>Tenants</h2>
          <form className="stack" onSubmit={createTenant}>
            <label>
              Slug
              <input
                value={tenantSlug}
                onChange={(event) => setTenantSlug(event.target.value)}
                placeholder="acme"
                required
                pattern="[a-z0-9][a-z0-9-]{1,62}"
              />
            </label>
            <label>
              Name
              <input
                value={tenantName}
                onChange={(event) => setTenantName(event.target.value)}
                placeholder="Acme org"
              />
            </label>
            <button type="submit" disabled={busy}>
              Create tenant
            </button>
          </form>
          <ul className="list">
            {tenants.map((tenant) => (
              <li key={tenant.id}>
                <button
                  type="button"
                  className={tenant.id === tenantId ? "pick on" : "pick"}
                  onClick={() => {
                    setTenantId(tenant.id);
                    setSelectedKeyId("");
                    setPlaintext("");
                  }}
                >
                  <strong>{tenant.name}</strong>
                  <span className="muted">{tenant.slug}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2>Mint key</h2>
          {tenantId && scopes ? (
            <KeyForm tenantId={tenantId} scopes={scopes} busy={busy} onMinted={onMinted} setBusy={setBusy} setError={setError} />
          ) : (
            <p className="muted">Create or select a tenant first.</p>
          )}
        </div>
      </section>

      {plaintext ? (
        <section className="card warn">
          <h2>API key — shown once</h2>
          <p>Store this in the password manager. Cloudiator will not show it again.</p>
          <pre className="key">{plaintext}</pre>
          <button
            type="button"
            onClick={async () => {
              await navigator.clipboard.writeText(plaintext);
              setCopied(true);
            }}
          >
            {copied ? "Copied" : "Copy key"}
          </button>
        </section>
      ) : null}

      <section className="card">
        <h2>Keys</h2>
        {!keys.length ? <p className="muted">No keys on this tenant yet.</p> : null}
        <ul className="list">
          {keys.map((key) => (
            <li key={key.id}>
              <button
                type="button"
                className={key.id === selectedKeyId ? "pick on" : "pick"}
                onClick={() => setSelectedKeyId(key.id)}
              >
                <strong>{key.name}</strong>
                <span className="muted">
                  {key.publicId} · {key.preset || "custom"}
                  {key.revokedAt ? " · revoked" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>

        {selectedKey ? (
          <div className="stack padded">
            <p>
              <code>sk-cld-{selectedKey.publicId}_…</code>
              {selectedKey.revokedAt ? <span className="badge">revoked</span> : null}
            </p>
            <p className="caps">{(selectedKey.capabilities || []).join(", ")}</p>
            <div className="row">
              <a className="button" href={api.openapiUrl(selectedKey.id)} download>
                Download OpenAPI JSON
              </a>
              <a className="button" href={api.openapiUrl(selectedKey.id, "salesforce")} download>
                Salesforce (External Services)
              </a>
            </div>
            <div className="revoke">
              <button type="button" className="danger" disabled={busy || selectedKey.revokedAt} onClick={revoke}>
                Revoke
              </button>
              <p className="muted">
                Revocation takes up to 60 seconds to propagate (worker key cache). Flush with{" "}
                <code>POST /v1/admin/cache/flush</code> on the Mini if it must be immediate.
              </p>
            </div>
          </div>
        ) : null}
      </section>

      <section className="grid">
        <div className="card">
          <div className="row spread">
            <h2>Usage</h2>
            <button type="button" onClick={() => refreshUsage(selectedKeyId).catch((err) => setError(err.message))}>
              Refresh
            </button>
          </div>
          <p className="muted">
            Reads the <code>usage_daily</code> rollup. A chat can take ~15s to appear after the Mini flushes its
            outbox.
          </p>
          <UsageChart days={chartDays} />
        </div>
        <SalesforcePanel apiUrl={me?.apiUrl || "https://api.cloudiator.org"} />
      </section>

      <Playground
        apiUrl={me?.apiUrl || "https://api.cloudiator.org"}
        model={me?.defaultModel || "gemma4:e4b-it-qat"}
        initialKey={playgroundKey}
      />
    </main>
  );
}
