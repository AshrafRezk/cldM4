import { apexSnippet, jsonBodyExample, namedCredentialSteps } from "./salesforceSnippets.js";
import { CopyButton } from "./SiteNav.jsx";

export function SalesforcePanel({ apiUrl }) {
  const url = apiUrl || "https://api.cloudiator.org";
  const steps = namedCredentialSteps(url);
  const apex = apexSnippet(url);
  const jsonBody = jsonBodyExample();
  return (
    <div className="card glass">
      <h2>Salesforce Named Credential + Apex</h2>
      <ol className="steps">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="muted">Paste into Anonymous Apex or a class. Timeout is 120s; stream is off.</p>
      <div className="snippet-head">
        <span>Apex</span>
        <CopyButton text={apex} />
      </div>
      <pre className="snippet">{apex}</pre>
      <div className="snippet-head">
        <span>JSON body the worker expects</span>
        <CopyButton text={jsonBody} />
      </div>
      <pre className="snippet">{jsonBody}</pre>
    </div>
  );
}
