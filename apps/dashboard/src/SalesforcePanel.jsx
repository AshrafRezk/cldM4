import { apexSnippet, jsonBodyExample, namedCredentialSteps } from "./salesforceSnippets.js";

export function SalesforcePanel({ apiUrl }) {
  const url = apiUrl || "https://api.cloudiator.org";
  const steps = namedCredentialSteps(url);
  const apex = apexSnippet(url);
  const jsonBody = jsonBodyExample();
  return (
    <div className="card">
      <h2>Salesforce Named Credential + Apex</h2>
      <ol className="steps">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="muted">Paste into Anonymous Apex or a class. Timeout is 120s; stream is off.</p>
      <pre className="snippet">{apex}</pre>
      <p className="muted">JSON body the worker expects:</p>
      <pre className="snippet">{jsonBody}</pre>
    </div>
  );
}
