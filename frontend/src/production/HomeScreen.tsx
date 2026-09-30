import { useEffect, useState } from "react";
import { getJson } from "../api";
import { fmtDuration } from "../format";
import { initials } from "./parts";

export interface Patient {
  id: string;
  name: string;
  age: number | null;
  height_cm: number | null;
  weight_kg: number | null;
  diagnosis: string;
  therapist_id: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

interface Today {
  sessions_today: number;
  avg_duration_s: number;
  patients: number;
  staff: number;
}

/** Where a therapist lands: start someone, or pick up where a patient left off. */
export function HomeScreen({ onNewPatient, onPickPatient, onManageStaff, onService }: {
  onNewPatient: () => void;
  onPickPatient: (p: Patient) => void;
  /** Technicians only: both are undefined for a therapist. */
  onManageStaff?: () => void;
  onService?: () => void;
}) {
  const [recent, setRecent] = useState<Patient[] | null>(null);
  const [today, setToday] = useState<Today | null>(null);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    getJson<Today>("/api/stats/today").then(setToday, () => setToday(null));
  }, []);

  useEffect(() => {
    const path = searching && query.trim()
      ? `/api/patients?q=${encodeURIComponent(query.trim())}`
      : "/api/patients/recent";
    const timer = setTimeout(() => {
      getJson<Patient[]>(path).then(setRecent, () => setRecent([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [query, searching]);

  return (
    <div className="prod-home">
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div className="prod-eyebrow">Start session</div>
        <div className="prod-start">
          <button className="hero" onClick={onNewPatient}>
            <div className="icon">＋</div>
            <strong>New Patient</strong>
            <small>Register and start a session</small>
          </button>
          <button className={searching ? "" : ""} onClick={() => setSearching((s) => !s)}>
            <div className="icon">⌕</div>
            <strong>Existing Patient</strong>
            <small>{searching ? "Showing search" : "Search by name or ID"}</small>
          </button>
        </div>

        {(onManageStaff || onService) && (
          <div style={{ marginTop: 22 }}>
            <div className="prod-eyebrow">Technician</div>
            <div style={{ display: "grid", gap: 10 }}>
              {onManageStaff && (
                <button className="prod-btn" style={{ justifyContent: "flex-start", textAlign: "left" }}
                  onClick={onManageStaff}>
                  Staff — add a therapist, reset a PIN
                </button>
              )}
              {onService && (
                <button className="prod-btn" style={{ justifyContent: "flex-start", textAlign: "left" }}
                  onClick={onService}>
                  Service — calibration and diagnostics
                </button>
              )}
            </div>
          </div>
        )}

        <div className="prod-tiles">
          <div className="prod-tile">
            <div className="n">{today?.sessions_today ?? "—"}</div>
            <div className="l">Sessions today</div>
          </div>
          <div className="prod-tile">
            <div className="n">{today ? fmtDuration(today.avg_duration_s) : "—"}</div>
            <div className="l">Avg duration</div>
          </div>
          <div className="prod-tile">
            <div className="n">{today?.patients ?? "—"}</div>
            <div className="l">Patients</div>
          </div>
          <div className="prod-tile">
            <div className="n">{today?.staff ?? "—"}</div>
            <div className="l">Staff</div>
          </div>
        </div>
      </div>

      <div style={{ minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
          <div className="prod-eyebrow" style={{ margin: 0 }}>
            {searching ? "Find a patient" : "Recent patients"}
          </div>
          <span className="muted" style={{ marginLeft: "auto", fontSize: 12 }}>
            Tap to start a session
          </span>
        </div>

        {searching && (
          <input
            className="prod-input"
            style={{ marginBottom: 14 }}
            placeholder="Name or patient ID"
            aria-label="Search patients"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        )}

        <div className="prod-patients">
          {recent === null && <div className="prod-empty">Loading…</div>}
          {recent?.length === 0 && (
            <div className="prod-empty">
              {searching && query ? "Nobody matches that." : "No patients yet. Start with New Patient."}
            </div>
          )}
          {recent?.map((p) => (
            <button key={p.id} className="prod-patient" onClick={() => onPickPatient(p)}>
              <div className="prod-avatar">{initials(p.name)}</div>
              <div className="who">
                <div className="name">
                  {p.name}<span className="pid">{p.id}</span>
                </div>
                <div className="meta">
                  {[
                    p.age ? `Age ${p.age}` : null,
                    p.height_cm ? `${p.height_cm} cm` : null,
                    p.weight_kg ? `${p.weight_kg} kg` : null,
                  ].filter(Boolean).join(" · ") || "No measurements recorded"}
                </div>
                {p.diagnosis && <span className="tag">{p.diagnosis}</span>}
              </div>
              <div className="go">›</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
