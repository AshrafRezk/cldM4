import { useState } from "react";
import { Logo } from "./Logo.jsx";
import { haptic } from "./haptic.js";

export function SiteNav({ go, path, email }) {
  const onConsole = path === "/console" || path.startsWith("/console/");
  return (
    <header className="nav">
      <button type="button" className="brand-btn" onClick={() => go("/")}>
        <Logo withWord size={30} />
      </button>
      <nav className="nav-links" aria-label="Primary">
        <button type="button" className={path === "/" ? "nav-link on" : "nav-link"} onClick={() => go("/")}>
          Product
        </button>
        <button type="button" className={onConsole ? "nav-link on" : "nav-link"} onClick={() => go("/console")}>
          Console
        </button>
      </nav>
      <div className="nav-end">
        {email ? <span className="who">{email}</span> : null}
        {!onConsole ? (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => go("/console")}>
            Open console
          </button>
        ) : null}
      </div>
    </header>
  );
}

export function CopyButton({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-ghost btn-sm"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        haptic("success");
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}
