import { Logo } from "./Logo.jsx";
import { SiteNav } from "./SiteNav.jsx";
import { haptic, magneticProps } from "./haptic.js";

const PILLARS = [
  {
    kicker: "Agentforce",
    title: "A private brain for every org",
    body: "Named Credentials, External Services 3.0.3, Apex at 120 seconds, stream off. Agentforce calls Cloudiator like any other Salesforce service — with a scoped key instead of a shared chatbot.",
  },
  {
    kicker: "On your metal",
    title: "Inference stays on the Mini",
    body: "Gemma 4 E4B for Arabic and English, one Metal slot, libraries before models. Prompts never hitch a ride through Netlify. The dashboard mints keys. The Mac Mini thinks.",
  },
  {
    kicker: "Scoped by construction",
    title: "Each key is a contract",
    body: "Chat, embeddings, OCR, maps, charts, DuckDB — only what that org is allowed to touch. Revoke it and the worker cache drops the key in under a minute.",
  },
];

const STEPS = [
  { n: "01", title: "Mint a scoped key", body: "Pick a tenant, a Salesforce-engineer preset, and the tools that org actually needs." },
  { n: "02", title: "Hang it on a Named Credential", body: "External Credential principal plus a permission set. No key in Apex. Timeout 120s. stream: false." },
  { n: "03", title: "Let Agentforce call home", body: "OpenAI-compatible /v1/chat/completions. Filtered OpenAPI for External Services. Usage rolls up in Neon." },
];

const PROOF = [
  { label: "API shape", value: "OpenAI-compatible" },
  { label: "Salesforce", value: "OAS 3.0.3" },
  { label: "Default model", value: "Gemma 4 E4B" },
  { label: "Languages", value: "Arabic + English" },
];

export function Landing({ go, path }) {
  return (
    <div className="page landing">
      <SiteNav go={go} path={path} />
      <main>
        <section className="hero">
          <p className="kicker reveal d1">Agentforce-native AI appliance</p>
          <h1 className="display reveal d2">
            Private AI.
            <span> For Agentforce.</span>
          </h1>
          <p className="lede reveal d3">
            Cloudiator is the always-on brain behind your Salesforce agents. Scoped <code>sk-cld-</code> keys, library-first
            tools, and a Mac Mini M4 that never ships prompts to someone else&apos;s GPU.
          </p>
          <div className="hero-actions reveal d4">
            <button type="button" className="btn btn-primary btn-lg btn-magnetic" {...magneticProps()} onClick={() => go("/console")}>
              Open the console
            </button>
            <a className="btn btn-ghost btn-lg" href="https://api.cloudiator.org/v1/health" target="_blank" rel="noreferrer" onClick={() => haptic("tap")}>
              Health of the Mini
            </a>
          </div>
          <div className="hero-stage reveal d5" aria-hidden="true">
            <Logo size={112} animated />
            <div className="orbit-ring" />
            <div className="orbit-ring delay" />
          </div>
        </section>

        <ul className="proof reveal d6">
          {PROOF.map((item) => (
            <li key={item.label}>
              <span className="proof-label">{item.label}</span>
              <strong>{item.value}</strong>
            </li>
          ))}
        </ul>

        <section className="pillars">
          {PILLARS.map((item) => (
            <article key={item.title} className="card glass lift">
              <p className="kicker">{item.kicker}</p>
              <h2>{item.title}</h2>
              <p className="muted">{item.body}</p>
            </article>
          ))}
        </section>

        <section className="how">
          <div className="section-head">
            <p className="kicker">How it plugs into Agentforce</p>
            <h2>Three steps. No shared password. No cloud GPU bill.</h2>
          </div>
          <ol className="how-grid">
            {STEPS.map((step) => (
              <li key={step.n} className="card glass">
                <span className="step-n">{step.n}</span>
                <h3>{step.title}</h3>
                <p className="muted">{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="honesty card glass">
          <p className="kicker">Straight talk</p>
          <h2>This is not ChatGPT. It is yours.</h2>
          <p className="muted">
            Cloudiator looks like a private OpenAI: a base URL, a scoped key, a filtered OpenAPI contract, and usage.
            The Mini orchestrates deterministic libraries when it can, and local models when language or vision is
            required. One Metal-heavy model at a time. Video is out of v1. Inference never runs on Netlify.
          </p>
        </section>
      </main>
      <footer className="site-foot">
        <Logo withWord size={22} animated={false} />
        <p>Keys in Neon. Inference on the Mini. Admin behind Cloudflare Access.</p>
      </footer>
    </div>
  );
}
