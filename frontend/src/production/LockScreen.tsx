import { useEffect, useState } from "react";
import { getJson, postJson } from "../api";
import { FirstRunSetup } from "./StaffScreen";
import { Keypad, initials } from "./parts";

export interface Staff {
  id: string;
  name: string;
  role: "therapist" | "technician";
  created_at: string;
}

/**
 * Signing in: tap your name, four digits.
 *
 * Not a username and password. This is a shared touch screen with no keyboard,
 * used several times a day by somebody whose hands are on a patient — a
 * password here becomes a sticky note on the monitor, which is worse than no
 * login at all. The PIN is for attribution and against casual misuse; the data
 * is protected by disk encryption, not by this.
 *
 * Stopping the machine must never require signing in, which is why the stop
 * control stays on this screen.
 */
export function LockScreen({ onSignedIn, onStopEverything }: {
  onSignedIn: (who: Staff) => void;
  onStopEverything?: () => void;
}) {
  const [staff, setStaff] = useState<Staff[] | null>(null);
  const [picked, setPicked] = useState<Staff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getJson<Staff[]>("/api/staff").then(setStaff, (e: Error) => setError(e.message));
  }, []);

  const signIn = async (pin: string) => {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await postJson<Staff>("/api/sign-in", { staff_id: picked.id, pin }));
    } catch (e) {
      setError((e as Error).message);
      setPicked(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="prod-lock">
      <div className="prod-lock-inner">
        <h1>Who is running this session?</h1>
        <p className="muted">Tap your name, then enter your PIN.</p>

        {error && <div className="prod-error" role="alert">{error}</div>}

        {staff === null && <p className="muted">Loading…</p>}

        {staff !== null && staff.length === 0 && (
          <FirstRunSetup onCreated={() => {
            getJson<Staff[]>("/api/staff").then(setStaff, () => undefined);
          }} />
        )}

        <div className="prod-staff">
          {(staff ?? []).map((s) => (
            <button key={s.id} className={picked?.id === s.id ? "on" : ""}
              onClick={() => { setPicked(s); setError(null); }}>
              <div className="prod-avatar">{initials(s.name)}</div>
              <div>{s.name}</div>
              <div className="role">{s.role}</div>
            </button>
          ))}
        </div>

        {onStopEverything && (
          <button className="prod-btn danger" style={{ marginTop: 34 }} onClick={onStopEverything}>
            Stop the treadmill
          </button>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          Stopping never needs a sign-in.
        </p>
      </div>

      {picked && !busy && (
        <Keypad
          title={`PIN for ${picked.name}`}
          mask
          onCancel={() => setPicked(null)}
          onDone={signIn}
        />
      )}
    </div>
  );
}
