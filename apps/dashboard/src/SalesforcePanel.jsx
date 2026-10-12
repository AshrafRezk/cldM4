import { useMemo, useState } from "react";
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

export function SalesforcePanel({ apiUrl, selectedKey, plaintext }) {
  const url = apiUrl || "https://api.cloudiator.org";
  const [serviceId, setServiceId] = useState("chat");
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

  return (
    <div className="sf-guide">
      <section className="card glass">
        <h2>Salesforce — plug and play</h2>
        <p className="muted">
          Install the unmanaged <strong>Cloudiator</strong> app from the repo (<code>salesforce/</code>), paste a minted
          key in <strong>Cloudiator Setup</strong>, then call every scoped service from Flows or Apex. Call outcomes land
          in <code>Cloudiator_Call_Log__c</code>. This is outbound Bearer auth — not a Salesforce Connected App.
        </p>
        <p className="muted">
          Full write-up: <code>docs/salesforce-app.md</code> · Named Credential detail: <code>docs/salesforce.md</code>
        </p>
      </section>

      <section className="card glass">
        <h2>1. Mint → install → configure</h2>
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
        {plaintext ? (
          <p className="card warn" style={{ marginTop: "1rem" }}>
            Fresh key in this browser session — paste it into <strong>Cloudiator Setup</strong> in the org now. It will
            not be shown again.
          </p>
        ) : (
          <p className="muted">Mint a Salesforce engineer key above if you do not have plaintext in hand.</p>
        )}
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
