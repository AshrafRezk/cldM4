import { useEffect, useState } from "react";
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

  async function save() {
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
        {(scopes.capabilities || []).map((cap) => {
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
      {saved ? <p className="muted">{saved}</p> : null}
    </fieldset>
  );
}
