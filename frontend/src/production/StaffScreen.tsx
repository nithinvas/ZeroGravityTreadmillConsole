import { useCallback, useEffect, useState } from "react";
import { getJson, postJson } from "../api";
import type { Staff } from "./LockScreen";
import { Keypad, initials } from "./parts";

/**
 * Onboarding staff: the screen a technician uses to add a therapist, reset a
 * forgotten PIN, or remove somebody who has left.
 *
 * A PIN is never recovered, only replaced — nothing here stores one in a form
 * that could be read back, which is the point of hashing it.
 */
export function StaffScreen({ me, onDone }: { me: Staff; onDone: () => void }) {
  const [staff, setStaff] = useState<Staff[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState<{ name: string; role: Staff["role"] } | null>(null);
  const [resetting, setResetting] = useState<Staff | null>(null);

  const reload = useCallback(() => {
    getJson<Staff[]>("/api/staff").then(setStaff, (e: Error) => setError(e.message));
  }, []);
  useEffect(reload, [reload]);

  const run = async (what: () => Promise<unknown>, said: string) => {
    setError(null);
    setNotice(null);
    try {
      await what();
      setNotice(said);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div style={{ padding: 26, maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
        <div>
          <h2 style={{ margin: 0 }}>Staff</h2>
          <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>
            Who can run sessions on this machine, and who can service it.
          </p>
        </div>
        <button className="prod-btn ghost" style={{ marginLeft: "auto" }} onClick={onDone}>Done</button>
      </div>

      {error && <div className="prod-error" role="alert">{error}</div>}
      {notice && (
        <div className="prod-error" style={{ color: "var(--accent)", background: "rgba(25,229,165,.08)", borderColor: "rgba(25,229,165,.35)" }}>
          {notice}
        </div>
      )}

      <div style={{ display: "grid", gap: 12, marginBottom: 22 }}>
        {(staff ?? []).map((s) => (
          <div key={s.id} className="prod-patient" style={{ cursor: "default" }}>
            <div className="prod-avatar">{initials(s.name)}</div>
            <div className="who">
              <div className="name">
                {s.name}
                {s.id === me.id && <span className="pid">you</span>}
              </div>
              <div className="prod-chips" style={{ marginTop: 4 }}>
                {(["therapist", "technician"] as const).map((r) => (
                  <button key={r} className={`prod-chip${s.role === r ? " on" : ""}`}
                    disabled={s.role === r || (s.id === me.id && r !== me.role)}
                    title={s.id === me.id && r !== me.role
                      ? "You cannot change your own role while signed in" : ""}
                    onClick={() => void run(
                      () => postJson(`/api/staff/${s.id}/role`, { role: r }),
                      `${s.name} is now a ${r}.`,
                    )}>
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <button className="prod-btn ghost" onClick={() => setResetting(s)}>Reset PIN</button>
            <button className="prod-btn ghost" style={{ color: "var(--danger)" }}
              disabled={s.id === me.id}
              title={s.id === me.id ? "You cannot remove yourself while signed in" : ""}
              onClick={() => {
                if (confirm(`Remove ${s.name}? Their past sessions keep their name.`)) {
                  void run(() => postJson(`/api/staff/${s.id}`, undefined, "DELETE"),
                           `${s.name} was removed.`);
                }
              }}>
              Remove
            </button>
          </div>
        ))}
        {staff?.length === 0 && <div className="prod-empty">Nobody is set up yet.</div>}
      </div>

      <div className="prod-card">
        <div className="prod-eyebrow">Add someone</div>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="prod-field" style={{ flex: 1, minWidth: 220 }}>
            <span>Full name</span>
            <input className="prod-input" placeholder="Dr. S. Mehta" maxLength={120}
              value={adding?.name ?? ""}
              onChange={(e) => setAdding({ role: adding?.role ?? "therapist", name: e.target.value })} />
          </label>
          <div className="prod-chips" style={{ paddingBottom: 6 }}>
            {(["therapist", "technician"] as const).map((r) => (
              <button key={r} className={`prod-chip${(adding?.role ?? "therapist") === r ? " on" : ""}`}
                onClick={() => setAdding({ name: adding?.name ?? "", role: r })}>
                {r}
              </button>
            ))}
          </div>
          <button className="prod-btn primary" disabled={!adding?.name.trim()}
            onClick={() => setAdding((a) => (a ? { ...a } : null))}>
            Set a PIN →
          </button>
        </div>
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
          A therapist runs sessions. A technician can also calibrate the machine and manage this
          list — a wrong coefficient makes every weight the machine reports wrong, so that is kept
          away from the clinical screens. Tap the role on anybody in the list above to change
          it — they keep their id, so their past sessions stay theirs.
        </p>
      </div>

      {adding?.name.trim() && (
        <Keypad
          title={`New PIN for ${adding.name.trim()}`}
          mask
          onCancel={() => setAdding(null)}
          onDone={(pin) => {
            const { name, role } = adding;
            setAdding(null);
            void run(() => postJson("/api/staff", { name: name.trim(), pin, role }),
                     `${name.trim()} can now sign in.`);
          }}
        />
      )}

      {resetting && (
        <Keypad
          title={`New PIN for ${resetting.name}`}
          mask
          onCancel={() => setResetting(null)}
          onDone={(pin) => {
            const who = resetting;
            setResetting(null);
            void run(() => postJson(`/api/staff/${who.id}/pin`, { pin }),
                     `${who.name}'s PIN was changed.`);
          }}
        />
      )}
    </div>
  );
}

/**
 * A machine with nobody on it cannot be signed into, so the first technician has
 * to be creatable from the lock screen itself. Offered only when the staff list
 * is genuinely empty.
 */
export function FirstRunSetup({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [pinFor, setPinFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="prod-card" style={{ marginTop: 24, textAlign: "left", maxWidth: 520, marginInline: "auto" }}>
      <strong>No staff are set up on this machine yet.</strong>
      <p className="muted">
        Create the first technician. They can calibrate the machine and add everyone else.
      </p>
      {error && <div className="prod-error" role="alert">{error}</div>}
      <div style={{ display: "flex", gap: 10 }}>
        <input className="prod-input" placeholder="Full name" value={name} maxLength={120}
          onChange={(e) => setName(e.target.value)} />
        <button className="prod-btn primary" disabled={!name.trim()}
          onClick={() => setPinFor(name.trim())}>
          Set a PIN
        </button>
      </div>
      {pinFor && (
        <Keypad
          title={`New PIN for ${pinFor}`}
          mask
          onCancel={() => setPinFor(null)}
          onDone={async (pin) => {
            setPinFor(null);
            setError(null);
            try {
              await postJson("/api/staff", { name: pinFor, pin, role: "technician" });
              onCreated();
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        />
      )}
    </div>
  );
}
