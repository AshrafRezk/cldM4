import { useMemo, useState } from "react";
import { api } from "./api.js";

const PRESET_LABELS = {
  salesforce_engineer: "Salesforce engineer",
  creative: "Creative",
  analyst: "Analyst",
  heavy: "Heavy (no 20B until Phase E)",
  speech: "Speech",
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
  }

  const boxes = useMemo(() => scopes.capabilities || [], [scopes]);

  async function submit(event) {
    event.preventDefault();
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
      <fieldset>
        <legend>Scopes</legend>
        {boxes.map((cap) => (
          <label key={cap} className="check">
            <input
              type="checkbox"
              checked={capabilities.includes(cap)}
              onChange={(event) => {
                setCapabilities((current) =>
                  event.target.checked ? [...current, cap] : current.filter((item) => item !== cap),
                );
              }}
            />
            {cap}
          </label>
        ))}
      </fieldset>
      <label>
        Salesforce org id (optional)
        <input value={salesforceOrgId} onChange={(event) => setSalesforceOrgId(event.target.value)} />
      </label>
      <button type="submit" disabled={busy || !capabilities.length}>
        Mint key
      </button>
    </form>
  );
}
