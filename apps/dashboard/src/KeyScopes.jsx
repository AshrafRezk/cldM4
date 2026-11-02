import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { haptic } from "./haptic.js";

/** Change the scopes of a key that is already in use. The key itself (the secret) stays the same. */
export function KeyScopes({ keyRow, scopes, busy, setBusy, setError, onSaved }) {
  const [capabilities, setCapabilities] = useState(keyRow.capabilities || []);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    setCapabilities(keyRow.capabilities || []);
    setSaved("");
  }, [keyRow.id, keyRow.capabilities]);

  const original = keyRow.capabilities || [];
  const changed =
    capabilities.length !== original.length || capabilities.some((cap) => !original.includes(cap));
  const boxes = useMemo(() => {
    const caps = [...(scopes.capabilities || [])];
    caps.sort((a, b) => Number(b === "voice") - Number(a === "voice"));
    return caps;
  }, [scopes]);

  async function save() {
    if (original.includes("voice") && !capabilities.includes("voice")) {
      const proceed = window.confirm("Remove voice? /v1/voice will return 403 once the worker cache expires.");
      if (!proceed) return;
    }
    setBusy(true);
    setError("");
    try {
      const body = await api.updateKey(keyRow.id, { capabilities });
      onSaved(body.key);
      setSaved(body.warning || "Saved.");
      haptic("success");
    } catch (err) {
      setError(err.message);
      haptic("warn");
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="stack">
      <legend>Scopes</legend>
      <div>
        {boxes.map((cap) => {
          const on = capabilities.includes(cap);
          return (
            <label key={cap} className={on ? "chip on" : "chip"}>
              <input
                type="checkbox"
                checked={on}
                disabled={busy}
                onChange={(event) => {
                  haptic("select");
                  setSaved("");
                  setCapabilities((current) =>
                    event.target.checked ? [...current, cap] : current.filter((item) => item !== cap),
                  );
                }}
              />
              {cap}
            </label>
          );
        })}
      </div>
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={busy || !changed || !capabilities.length} onClick={save}>
          Save scopes
        </button>
        {changed ? (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setCapabilities(original)}>
            Undo
          </button>
        ) : null}
      </div>
      {capabilities.includes("voice") ? null : (
        <p className="error">
          Voice is off, so /v1/voice returns 403. Tick voice and save. The secret already in Salesforce stays valid.
        </p>
      )}
      {saved ? <p className="muted">{saved}</p> : null}
    </fieldset>
  );
}
