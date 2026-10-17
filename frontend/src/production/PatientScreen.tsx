import { useEffect, useState } from "react";
import { getJson } from "../api";
import { fmtDuration } from "../format";
import type { Patient } from "./HomeScreen";
import { initials } from "./parts";

/**
 * Everything on file for one patient: who they are, and every session they
 * have done here.
 *
 * Until now tapping a patient went straight into the wizard, so a finished
 * report could never be opened again -- the files were on disk and the API
 * would serve them, but nothing in the interface could get back. A therapist
 * could not answer "how did she do last week?" at the machine.
 */

interface PastSession {
  id: string;
  started_at: string;
  duration_s: number;
  walking_s: number;
  distance_m: number;
  steps_accepted: number;
  main_cadence: number | null;
  main_step_length: number | null;
  status: string;
}

interface PatientFull extends Patient {
  sessions: PastSession[];
}

export function PatientScreen({ patientId, onStart, onOpenSession, onBack }: {
  patientId: string;
  onStart: (p: Patient) => void;
  onOpenSession: (sessionId: string) => void;
  onBack: () => void;
}) {
  const [p, setP] = useState<PatientFull | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<PatientFull>(`/api/patients/${encodeURIComponent(patientId)}`)
      .then(setP, (e: Error) => setError(e.message));
  }, [patientId]);

  if (error) return <div className="prod-error" role="alert">{error}</div>;
  if (!p) return <div className="prod-empty">Loading…</div>;

  const sessions = [...(p.sessions ?? [])].sort((a, b) => b.started_at.localeCompare(a.started_at));
  const trend = sessions.filter((s) => s.main_cadence).slice(0, 12).reverse();

  return (
    <div style={{ padding: 22, maxWidth: 1080, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
        <div className="prod-avatar" style={{ width: 52, height: 52, fontSize: 18 }}>{initials(p.name)}</div>
        <div>
          <h2 style={{ margin: 0 }}>{p.name}<span className="pid" style={{ marginLeft: 10 }}>{p.id}</span></h2>
          <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>
            {[p.age ? `Age ${p.age}` : null, p.height_cm ? `${p.height_cm} cm` : null,
              p.weight_kg ? `${p.weight_kg} kg` : null, p.diagnosis || null]
              .filter(Boolean).join(" · ") || "No details recorded"}
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <button className="prod-btn ghost" onClick={onBack}>Back</button>
          <button className="prod-btn primary big" onClick={() => onStart(p)}>Start session</button>
        </div>
      </div>

      {trend.length > 2 && <CadenceTrend sessions={trend} />}

      <div className="prod-eyebrow" style={{ marginTop: 18 }}>
        Previous sessions{sessions.length ? ` (${sessions.length})` : ""}
      </div>

      {sessions.length === 0 && (
        <div className="prod-empty">
          No sessions yet. Tap <strong>Start session</strong> to record the first one.
        </div>
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {sessions.map((s) => (
          <button key={s.id} className="prod-patient" onClick={() => onOpenSession(s.id)}>
            <div className="who">
              <div className="name">
                {new Date(s.started_at).toLocaleDateString(undefined,
                  { weekday: "short", day: "numeric", month: "short" })}
                <span className="pid">
                  {new Date(s.started_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                </span>
                {s.status !== "completed" && (
                  <span className="tag" style={{ color: "var(--danger)" }}>{s.status}</span>
                )}
              </div>
              <div className="meta">
                {[
                  fmtDuration(s.duration_s),
                  `${s.steps_accepted ?? 0} steps`,
                  s.distance_m ? `${s.distance_m.toFixed(1)} m` : null,
                  s.main_cadence ? `${s.main_cadence.toFixed(0)} steps/min` : null,
                  s.main_step_length ? `${s.main_step_length.toFixed(2)} m step` : null,
                ].filter(Boolean).join(" · ")}
              </div>
            </div>
            <div className="go">›</div>
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Cadence over the last dozen sessions.
 *
 * One session's numbers are a data point; a run of them is the recovery story,
 * and it is the only view here that answers "is this working?".
 */
function CadenceTrend({ sessions }: { sessions: PastSession[] }) {
  const vals = sessions.map((s) => s.main_cadence as number);
  const lo = Math.min(...vals) * 0.9;
  const hi = Math.max(...vals) * 1.05;
  const w = 100, h = 34;
  const pts = vals.map((v, i) => {
    const x = vals.length > 1 ? (i / (vals.length - 1)) * w : w / 2;
    return `${x},${h - ((v - lo) / (hi - lo || 1)) * h}`;
  }).join(" ");
  const first = vals[0], last = vals[vals.length - 1];
  const change = ((last - first) / first) * 100;

  return (
    <div className="prod-card" style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <div>
        <div className="prod-eyebrow" style={{ marginBottom: 2 }}>Cadence trend</div>
        <div style={{ fontSize: 21, fontWeight: 700 }}>
          {last.toFixed(0)} <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>steps/min</span>
        </div>
        <div className="muted" style={{ fontSize: 12 }}>
          {change >= 0 ? "+" : ""}{change.toFixed(0)}% over {vals.length} sessions
        </div>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
           style={{ flex: 1, height: 48 }} aria-label="Cadence across recent sessions">
        <polyline points={pts} fill="none" stroke="var(--accent, #19e5a5)" strokeWidth="2"
                  vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}
