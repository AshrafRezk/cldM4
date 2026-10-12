import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import {
  SERVICES,
  apexNamedCredentialSnippet,
  apexSnippet,
  installSteps,
  namedCredentialSteps,
  openApiCurl,
} from "./salesforceSnippets.js";
import { CopyButton } from "./SiteNav.jsx";

export function SalesforcePanel({ apiUrl, selectedKey, plaintext, installBanner }) {
  const url = apiUrl || "https://api.cloudiator.org";
  const [serviceId, setServiceId] = useState("chat");
  const [install, setInstall] = useState(null);
  const [installError, setInstallError] = useState("");
  const [loginTarget, setLoginTarget] = useState("login");
  const [connectKey, setConnectKey] = useState(plaintext || "");
  const [busyInstall, setBusyInstall] = useState(false);
  const service = SERVICES.find((row) => row.id === serviceId) || SERVICES[0];
  const stepsNc = namedCredentialSteps(url);
  const stepsInstall = installSteps();
  const apexPkg = apexSnippet(url);
  const apexNc = apexNamedCredentialSnippet();
  const keyHint = connectKey || plaintext || "sk-cld-…";
  const curlOas = openApiCurl(url, keyHint);
  const bodyJson = useMemo(
    () => (service.body ? JSON.stringify(service.body, null, 2) : "// not available yet"),
    [service],
  );

  useEffect(() => {
    api
      .salesforceInstallStatus()
      .then(setInstall)
      .catch((err) => setInstallError(err.message));
  }, []);

  useEffect(() => {
    // Fresh mint fills the field; existing keys stay whatever the operator pastes.
    if (plaintext) setConnectKey(plaintext);
  }, [plaintext]);

  async function startInstall(configureOnly) {
    setInstallError("");
    const apiKey = connectKey.trim();
    if (configureOnly && !apiKey) {
      setInstallError("Paste an existing sk-cld-… key (from your password manager) to connect it.");
      return;
    }
    if (apiKey && !/^sk-cld-[a-z0-9]+_[A-Za-z0-9_-]+$/.test(apiKey)) {
      setInstallError("API key must look like sk-cld-{public_id}_{secret}.");
      return;
    }
    if (
      apiKey &&
      selectedKey?.publicId &&
      !apiKey.startsWith(`sk-cld-${selectedKey.publicId}_`)
    ) {
      setInstallError(
        `This key does not match the selected key public id (${selectedKey.publicId}). Select the matching key or paste the right secret.`,
      );
      return;
    }
    setBusyInstall(true);
    try {
      const result = await api.startSalesforceInstall({
        login: loginTarget,
        apiKey: apiKey || undefined,
        baseUrl: url,
        configureOnly: Boolean(configureOnly),
      });
      if (!result?.redirectUrl) throw new Error("No redirect URL from install start.");
      window.location.href = result.redirectUrl;
    } catch (err) {
      if (!configureOnly && install?.packageInstallUrl && !apiKey) {
        window.location.href = api.salesforceInstallStartUrl(loginTarget);
        return;
      }
      setInstallError(err.message);
      setBusyInstall(false);
    }
  }

  return (
    <div className="sf-guide">
      {installBanner ? (
        <section className={installBanner.ok ? "card glass" : "card glass warn"}>
          <h2>
            {installBanner.ok
              ? installBanner.mode === "connect"
                ? "Salesforce key connected"
                : "Salesforce package installed"
              : "Salesforce install issue"}
          </h2>
          <p className="muted">{installBanner.text}</p>
        </section>
      ) : null}

      <section className="card glass lift">
        <h2>Install / connect Salesforce</h2>
        <p className="muted">
          Salesforce logs you in. Deploy the app (or connect a key to an org that already has it). The key is written into
          org <strong>Cloudiator Setup</strong> so Salesforce can call the Mini. Works for a fresh mint or an existing key
          from your password manager.
        </p>
        {selectedKey ? (
          <p className="muted">
            Selected key: <code>sk-cld-{selectedKey.publicId}_…</code>
            {selectedKey.revokedAt ? " (revoked)" : ""}
          </p>
        ) : (
          <p className="muted">Select a key above, or paste any sk-cld-… secret below.</p>
        )}
        {installError ? <p className="card warn">{installError}</p> : null}
        {install ? (
          <>
            <label className="field">
              <span>API key to put in the org</span>
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder={
                  selectedKey
                    ? `Paste full secret for sk-cld-${selectedKey.publicId}_…`
                    : "sk-cld-… (fresh mint or existing)"
                }
                value={connectKey}
                onChange={(event) => setConnectKey(event.target.value)}
              />
            </label>
            {plaintext && connectKey === plaintext ? (
              <p className="muted">Using the key minted in this browser session.</p>
            ) : null}
            <label className="field">
              <span>Org type</span>
              <select value={loginTarget} onChange={(event) => setLoginTarget(event.target.value)}>
                <option value="login">Production / Developer Edition</option>
                <option value="test">Sandbox</option>
              </select>
            </label>
            <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
              <button
                type="button"
                className="btn"
                disabled={!install.oneClick || busyInstall}
                onClick={() => startInstall(false)}
              >
                Install &amp; connect
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={!install.oauthReady || busyInstall || !connectKey.trim()}
                onClick={() => startInstall(true)}
              >
                Connect existing key only
              </button>
              <a className="btn btn-ghost" href={install.zipDownloadPath || "/salesforce/cloudiator-unmanaged.zip"} download>
                Download zip
              </a>
            </div>
            {install.needsPublicConfig ? (
              <p className="card warn" style={{ marginTop: "0.85rem" }}>
                One product setting left (not a Netlify secret): put a public <code>04t…</code> package id or Connected
                App <strong>Consumer Key</strong> (PKCE, no secret) in{" "}
                <code>apps/dashboard/netlify/functions/_lib/sfInstallConfig.json</code>. See{" "}
                <code>docs/salesforce-app.md</code>.
              </p>
            ) : (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                <strong>Install &amp; connect</strong> deploys the unmanaged app + writes the key.{" "}
                <strong>Connect existing key only</strong> skips deploy (org already has Cloudiator) and only updates Setup.
              </p>
            )}
          </>
        ) : (
          <p className="muted">Checking install configuration…</p>
        )}
      </section>

      <section className="card glass">
        <h2>Salesforce — plug and play</h2>
        <p className="muted">
          The unmanaged <strong>Cloudiator</strong> app stores your minted key in protected config, exposes Flow
          actions, and writes <code>Cloudiator_Call_Log__c</code>. Outbound auth is Bearer / Named Credential — not a
          Salesforce Connected App for callouts (the Connected App above is only for this install OAuth).
        </p>
        <p className="muted">
          Full write-up: <code>docs/salesforce-app.md</code> · Named Credential detail: <code>docs/salesforce.md</code>
        </p>
      </section>

      <section className="card glass">
        <h2>1. Mint or reconnect → install → configure</h2>
        <ol className="steps">
          <li>Mint a Salesforce engineer key, or select an existing one and paste the full <code>sk-cld-…</code> from your password manager.</li>
          <li>
            <strong>Install &amp; connect</strong> (first deploy) or <strong>Connect existing key only</strong> (org already has the app).
          </li>
          <li>Confirm in the org: App Launcher → Cloudiator → Setup → Test /v1/health (key should already be written).</li>
          <li>Build Flows with Cloudiator:* actions; inspect Call Logs.</li>
        </ol>
        <details>
          <summary className="muted">CLI / Workbench fallback</summary>
          <ol className="steps">
            {stepsInstall.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <div className="snippet-head">
            <span>CLI deploy</span>
            <CopyButton
              text={`cd salesforce\nsf project deploy start --source-dir force-app --target-org myorg\nsf org assign permset --name Cloudiator_Admin --target-org myorg`}
            />
          </div>
          <pre className="snippet">{`cd salesforce
sf project deploy start --source-dir force-app --target-org myorg
sf org assign permset --name Cloudiator_Admin --target-org myorg`}</pre>
        </details>
        {plaintext ? (
          <p className="card warn" style={{ marginTop: "1rem" }}>
            Fresh key in this browser session — paste it into <strong>Cloudiator Setup</strong> in the org after install.
          </p>
        ) : null}
      </section>

      <section className="card glass">
        <h2>2. API contract (OpenAPI 3.0.3)</h2>
        <p className="muted">
          External Services and the packaged Flow actions share this contract. Use <code>?target=salesforce</code> only —
          plain OpenAPI 3.1 may fail the importer.
        </p>
        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
          {selectedKey?.id ? (
            <>
              <a className="btn btn-ghost" href={api.openapiUrl(selectedKey.id, "salesforce")} download>
                Download Salesforce OpenAPI
              </a>
              <a className="btn btn-ghost" href={api.openapiUrl(selectedKey.id)} download>
                Download full OpenAPI 3.1
              </a>
            </>
          ) : (
            <p className="muted">Select a key above to enable downloads.</p>
          )}
        </div>
        <div className="snippet-head">
          <span>curl</span>
          <CopyButton text={curlOas} />
        </div>
        <pre className="snippet">{curlOas}</pre>
      </section>

      <section className="card glass">
        <h2>3. Services & modalities</h2>
        <p className="muted">
          Text, image, and document paths are live on the engineer preset. Audio/speech waits on Phase G. FLUX jobs need
          an <code>image_generation</code> scope.
        </p>
        <label className="field">
          <span>Service</span>
          <select value={serviceId} onChange={(event) => setServiceId(event.target.value)}>
            {SERVICES.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name} — {row.modality}
              </option>
            ))}
          </select>
        </label>
        <dl className="sf-meta">
          <div>
            <dt>HTTP</dt>
            <dd>
              <code>{service.path}</code>
            </dd>
          </div>
          <div>
            <dt>Flow</dt>
            <dd>{service.flow}</dd>
          </div>
          <div>
            <dt>Modality</dt>
            <dd>{service.modality}</dd>
          </div>
        </dl>
        {service.note ? <p className="card warn">{service.note}</p> : null}
        <div className="snippet-head">
          <span>Example JSON body</span>
          <CopyButton text={bodyJson} />
        </div>
        <pre className="snippet">{bodyJson}</pre>
      </section>

      <section className="card glass">
        <h2>4. Apex</h2>
        <p className="muted">Packaged helper (logs automatically):</p>
        <div className="snippet-head">
          <span>CloudiatorService.chat</span>
          <CopyButton text={apexPkg} />
        </div>
        <pre className="snippet">{apexPkg}</pre>
        <p className="muted">Raw Named Credential callout:</p>
        <div className="snippet-head">
          <span>callout:Cloudiator</span>
          <CopyButton text={apexNc} />
        </div>
        <pre className="snippet">{apexNc}</pre>
      </section>

      <section className="card glass">
        <h2>5. Named Credential (recommended hardening)</h2>
        <ol className="steps">
          {stepsNc.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <section className="card glass">
        <h2>6. Call logs</h2>
        <p className="muted">
          Object <code>Cloudiator_Call_Log__c</code>: Service, Status (Success/Failure), Modality In/Out, HTTP status,{" "}
          <code>X-Request-Id</code>, duration, truncated input/output, artifact id, optional related record. Every
          packaged Flow action and <code>CloudiatorService</code> write a row.
        </p>
      </section>
    </div>
  );
}
