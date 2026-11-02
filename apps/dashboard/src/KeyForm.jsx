import { useMemo, useState } from "react";
import { api } from "./api.js";
import { haptic } from "./haptic.js";

const PRESET_LABELS = {
  salesforce_engineer: "Salesforce engineer (includes voice)",
  voice_intake: "Voice intake (chat + voice)",
  creative: "Creative",
  analyst: "Analyst",
  heavy: "Heavy (no 20B until Phase E)",
  speech: "Speech (transcriptions — not phone voice)",
};

export function KeyForm({ tenantId, scopes, busy, onMinted, setBusy, setError }) {
  const presetNames = Object.keys(scopes.presets || {});
  const [preset, setPreset] = useState("salesforce_engineer");
  const [name, setName] = useState("Salesforce org");
  const [capabilities, setCapabilities] = useState(() => [
    ...(scopes.presets.salesforce_engineer?.capabilities || []),
  ]);
  const [salesforceOrgId, setSalesforceOrgId] = useState("");

  const forceNoStream = Boolean(scopes.presets[preset]?.force_no_stream);

  function applyPreset(next) {
    setPreset(next);
    const spec = scopes.presets[next];
    setCapabilities([...(spec?.capabilities || [])]);
    haptic("select");
  }

  const boxes = useMemo(() => {
    const caps = [...(scopes.capabilities || [])];
    caps.sort((a, b) => Number(b === "voice") - Number(a === "voice"));
    return caps;
  }, [scopes]);
  const voiceKnown = boxes.includes("voice");
  const voiceOn = capabilities.includes("voice");

  async function submit(event) {
    event.preventDefault();
    const presetCaps = scopes.presets[preset]?.capabilities || [];
    if (presetCaps.includes("voice") && !capabilities.includes("voice")) {
      const proceed = window.confirm(
        "Voice is unticked. Phone calls and /v1/voice will return 403. Mint this key without voice?",
      );
      if (!proceed) return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.mintKey(tenantId, {
        name,
        preset,
        capabilities,
        salesforceOrgId: salesforceOrgId || undefined,
        forceNoStream,
      });
      onMinted(result);
    } catch (err) {
      setError(err.message);
      haptic("warn");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <label>
        Key name
        <input value={name} onChange={(event) => setName(event.target.value)} required />
      </label>
      <label>
        Preset
        <select value={preset} onChange={(event) => applyPreset(event.target.value)}>
          {presetNames.map((item) => (
            <option key={item} value={item}>
              {PRESET_LABELS[item] || item}
            </option>
          ))}
        </select>
      </label>
      {voiceKnown && !voiceOn ? (
        <p className="error">Voice is off. Salesforce voice routes return 403 until it is ticked.</p>
      ) : null}
      {voiceKnown ? null : (
        <p className="error">
          This console has no voice scope, so it is older than the repo. On the Mini, pull and run{" "}
          <code>python -m app.dbtool set-capabilities --add voice</code>. The secret stays the same.
        </p>
      )}
      <fieldset>
        <legend>Scopes</legend>
        {boxes.map((cap) => {
          const on = capabilities.includes(cap);
          return (
            <label key={cap} className={on ? "chip on" : "chip"}>
              <input
                type="checkbox"
                checked={on}
                onChange={(event) => {
                  haptic("select");
                  setCapabilities((current) =>
                    event.target.checked ? [...current, cap] : current.filter((item) => item !== cap),
                  );
                }}
              />
              {cap}
            </label>
          );
        })}
      </fieldset>
      <label>
        Salesforce org id (optional)
        <input value={salesforceOrgId} onChange={(event) => setSalesforceOrgId(event.target.value)} />
      </label>
      <button type="submit" className="btn btn-primary" disabled={busy || !capabilities.length}>
        Mint key
      </button>
    </form>
  );
}
