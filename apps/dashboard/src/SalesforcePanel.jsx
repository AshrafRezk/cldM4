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
  const service = SERVICES.find((row) => row.id === serviceId) || SERVICES[0];
  const stepsNc = namedCredentialSteps(url);
  const stepsInstall = installSteps();
  const apexPkg = apexSnippet(url);
  const apexNc = apexNamedCredentialSnippet();
  const keyHint = plaintext || "sk-cld-…";
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

  function startInstall() {
    // Full navigation so Set-Cookie + Salesforce redirect work.
    window.location.href = api.salesforceInstallStartUrl(loginTarget);
  }

  return (
    <div className="sf-guide">
      {installBanner ? (
        <section className={installBanner.ok ? "card glass" : "card glass warn"}>
          <h2>{installBanner.ok ? "Salesforce package installed" : "Salesforce install issue"}</h2>
          <p className="muted">{installBanner.text}</p>
        </section>
      ) : null}

      <section className="card glass lift">
        <h2>Install into Salesforce</h2>
        <p className="muted">
          One click: authenticate to your org, then Cloudiator deploys the unmanaged app (Setup, Flow actions, call
          logs). Afterward, paste your minted key in <strong>Cloudiator Setup</strong> inside Salesforce.
        </p>
        {installError ? <p className="card warn">{installError}</p> : null}
        {install ? (
          <>
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
                disabled={!install.oneClick}
                onClick={startInstall}
              >
                {install.packageInstallUrl ? "Install package (Salesforce login)" : "Connect Salesforce & install"}
              </button>
              <a className="btn btn-ghost" href={install.zipDownloadPath || "/salesforce/cloudiator-unmanaged.zip"} download>
                Download zip
              </a>
            </div>
            {!install.oneClick ? (
              <p className="card warn" style={{ marginTop: "0.85rem" }}>
                One-click is off until Netlify has <code>SF_OAUTH_CLIENT_ID</code> +{" "}
                <code>SF_OAUTH_CLIENT_SECRET</code> (Connected App callback{" "}
                <code>{install.callbackUrl}</code>), or <code>SF_PACKAGE_VERSION_ID</code> (04t…). See{" "}
                <code>docs/salesforce-app.md</code>.
              </p>
            ) : (
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                {install.packageInstallUrl
                  ? "Uses Salesforce’s native package installer (you pick the org after login)."
                  : "OAuth → Metadata deploy of the unmanaged package → assigns Cloudiator Admin when possible."}
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
        <h2>1. Mint → install → configure</h2>
        <ol className="steps">
          <li>Mint a Salesforce engineer key in this Console (copy plaintext once).</li>
          <li>Click <strong>Connect Salesforce &amp; install</strong> above (or download zip / CLI).</li>
          <li>In the org: App Launcher → Cloudiator → Setup → paste key → Test /v1/health.</li>
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
