import { useEffect, useRef, useState } from "react";
import { postJson } from "../api";
import { fmtDuration, fmtNum } from "../format";
import type { Snapshot, SessionLive, SessionSummary, TreadmillState } from "../types";
import { LiveChart } from "./LiveChart";
import { HeightPanel } from "./HeightPanel";
import { LiveGaitChart } from "./LiveGaitChart";
import { TreadmillPanel } from "./TreadmillPanel";

const ACTIVITIES = ["walk", "jog", "run"];
const CONFIDENCE_TEXT: Record<string, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
  unavailable: "Unavailable",
};

interface Props {
  snapshot: Snapshot;
  onOpenReport: (id: string) => void;
  onCalibrate: () => void;
}

export function SessionPage({ snapshot, onOpenReport, onCalibrate }: Props) {
  const [finished, setFinished] = useState<{ id: string; summary: SessionSummary } | null>(null);
  if (snapshot.session) {
    return (
      <ActiveSession
        session={snapshot.session}
        treadmill={snapshot.treadmill}
        onFinished={(id, summary) => setFinished({ id, summary })}
      />
    );
  }
  return (
    <div className="stack">
      {finished && (
        <section className="panel notice-panel" role="status">
          <h2>Session saved</h2>
          <p>
            {finished.summary.steps_accepted} accepted steps, {fmtDuration(finished.summary.walking_s)} walking,{" "}
            {fmtNum(finished.summary.distance_m, 1)} m.
          </p>
          <button className="btn primary" onClick={() => onOpenReport(finished.id)}>Open the report</button>
        </section>
      )}
      <SessionSetup snapshot={snapshot} onCalibrate={onCalibrate} />
      <HeightPanel height={snapshot.height} />
      <TreadmillPanel treadmill={snapshot.treadmill} />
    </div>
  );
}

function SessionSetup({ snapshot, onCalibrate }: { snapshot: Snapshot; onCalibrate: () => void }) {
  const t = snapshot.treadmill;
  const controlled = t.connected && t.has_control;
  const [form, setForm] = useState({
    patient_name: "", patient_id: "", issue: "", tester: "", speed_kph: "3.0", activity: "walk",
    body_weight_kg: "", bws_percent: "", notes: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [offerManual, setOfferManual] = useState(false);
  const noCoefficients = snapshot.calibration.status === "missing";
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });

  const start = async (withoutTreadmill = false) => {
    setError(null);
    setBusy(true);
    try {
      await postJson("/api/sessions", {
        ...form,
        speed_kph: Number(form.speed_kph),
        body_weight_kg: form.body_weight_kg ? Number(form.body_weight_kg) : null,
        bws_percent: form.bws_percent ? Number(form.bws_percent) : null,
        without_treadmill: withoutTreadmill,
      });
      setOfferManual(false);
    } catch (e) {
      setError((e as Error).message);
      // The backend refuses a first attempt with no belt control, so the choice to
      // go ahead anyway is made deliberately rather than discovered mid-session.
      if (!withoutTreadmill && !controlled) setOfferManual(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>New session</h2>
      {noCoefficients && (
        <div className="warning severe">
          <span className="warning-icon" aria-hidden="true">!</span>
          <span>
            No coefficients are selected, so loads and gait cannot be computed.{" "}
            <button className="btn ghost" onClick={onCalibrate}>Choose coefficients</button>
          </span>
        </div>
      )}
      <div className="form-grid">
        <label>Patient name<input value={form.patient_name} onChange={set("patient_name")} maxLength={120} /></label>
        <label>Patient ID<input value={form.patient_id} onChange={set("patient_id")} maxLength={60} /></label>
        <label className="wide">Issue / clinical description
          <input value={form.issue} onChange={set("issue")} maxLength={500} />
        </label>
        <label>Tester<input value={form.tester} onChange={set("tester")} maxLength={120} /></label>
        {controlled ? (
          <label>Starting belt speed
            <input value={`${fmtNum(t.session_start_speed_kph, 1)} km/h`} readOnly aria-readonly="true" />
          </label>
        ) : (
          <label>Belt speed (km/h)<input inputMode="decimal" value={form.speed_kph} onChange={set("speed_kph")} /></label>
        )}
        <label>Activity
          <select value={form.activity} onChange={set("activity")}>
            {ACTIVITIES.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label>Body weight (kg, optional)
          <input inputMode="decimal" value={form.body_weight_kg} onChange={set("body_weight_kg")} />
        </label>
        <label>Body-weight support (%, optional)
          <input inputMode="decimal" value={form.bws_percent} onChange={set("bws_percent")} />
        </label>
        <label className="wide">Notes<textarea value={form.notes} onChange={set("notes")} maxLength={2000} /></label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="btn primary big" onClick={() => start()} disabled={busy || noCoefficients}>
        {busy ? "Starting…" : controlled ? "Start session and belt" : "Start session"}
      </button>
      {offerManual && (
        <button className="btn ghost" onClick={() => start(true)} disabled={busy}>
          Start without belt control
        </button>
      )}
      <p className="hint">
        {controlled
          ? `The belt starts at ${fmtNum(t.session_start_speed_kph, 1)} km/h and is raised with the + button ` +
            "once the patient is walking. Cadence and lengths follow the speed you set, so the two can never disagree."
          : "Cadence and lengths use the belt speed entered here, so update it whenever the treadmill changes."}{" "}
        Everything is saved on this computer as the session runs: every sample, every step, and a summary
        per speed.
      </p>
    </section>
  );
}

function ActiveSession({ session, treadmill, onFinished }: {
  session: SessionLive;
  treadmill: TreadmillState;
  onFinished: (id: string, s: SessionSummary) => void;
}) {
  const g = session.gait;
  const c = session.condition;
  const controlled = treadmill.connected && treadmill.has_control;
  const [speed, setSpeed] = useState(String(c.speed_kph ?? ""));
  const [activity, setActivity] = useState(c.activity);
  const [bws, setBws] = useState(c.bws_percent === null ? "" : String(c.bws_percent));
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSpeed(String(c.speed_kph ?? ""));
    setActivity(c.activity);
  }, [c.id, c.speed_kph, c.activity]);

  const apply = async (kph: number) => {
    setError(null);
    try {
      await postJson("/api/sessions/current/condition", {
        speed_kph: kph, activity, bws_percent: bws ? Number(bws) : null,
      });
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const nudge = (delta: number) => {
    const next = Math.max(0, Math.round((Number(speed) + delta) * 10) / 10);
    setSpeed(String(next));
    void apply(next);
  };
  const stop = async () => {
    try {
      const result = await postJson<{ meta: { id: string }; summary: SessionSummary }>(
        "/api/sessions/current/stop", { notes },
      );
      onFinished(result.meta.id, result.summary);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="stack">
      <section className="panel session-head">
        <div>
          <h2>{session.details.patient_name || session.details.patient_id}</h2>
          <p className="muted">
            {session.details.patient_id && `${session.details.patient_id} · `}
            {session.details.tester && `tester ${session.details.tester} · `}
            recording {fmtDuration(session.elapsed_s)}
          </p>
        </div>
        <div className="pill pill-streaming"><span className="rec-dot" /> Recording</div>
      </section>

      <section className="metrics">
        <Metric label="Cadence" value={fmtNum(g.cadence_spm, 1)} unit="steps/min" />
        <Metric label="Step length" value={fmtNum(g.step_length_m, 2)} unit="m" />
        <Metric label="Stride length" value={fmtNum(g.stride_length_m, 2)} unit="m" />
      </section>
      <div className={`gait-status ${g.confidence ?? "none"}`}>
        {g.prompt ?? (g.confidence ? CONFIDENCE_TEXT[g.confidence] : "")}
        <span className="muted">
          {" "}· {g.steps_accepted} of {g.steps_total} steps accepted · walking {fmtDuration(session.walking_s)} ·{" "}
          {fmtNum(session.distance_m, 1)} m
        </span>
      </div>

      {controlled && <TreadmillPanel treadmill={treadmill} compact />}

      <section className="panel">
        <h2>Condition {c.id} <span className="muted">
          · {c.speed_kph === null ? "belt stopped" : `${c.speed_kph} km/h`} · {c.activity}
          {c.bws_percent !== null ? ` · BWS ${c.bws_percent}%` : ""}</span></h2>
        {controlled ? (
          <>
            <div className="speed-control">
              <label>Activity
                <select value={activity} onChange={(e) => setActivity(e.target.value)}>
                  {ACTIVITIES.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </label>
              <label>BWS (%)<input inputMode="decimal" value={bws} onChange={(e) => setBws(e.target.value)} /></label>
              <button className="btn" onClick={() => apply(c.speed_kph ?? 0)}>Apply</button>
            </div>
            <p className="hint">
              Speed and incline are on the treadmill panel above, and every change there starts a new
              condition at that speed. Activity and body-weight support are recorded here.
            </p>
          </>
        ) : (
        <div className="speed-control">
          <button className="btn big" onClick={() => nudge(-0.1)} aria-label="Slower">−0.1</button>
          <label>Belt speed (km/h)<input inputMode="decimal" value={speed} onChange={(e) => setSpeed(e.target.value)} /></label>
          <button className="btn big" onClick={() => nudge(0.1)} aria-label="Faster">+0.1</button>
          <label>Activity
            <select value={activity} onChange={(e) => setActivity(e.target.value)}>
              {ACTIVITIES.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <label>BWS (%)<input inputMode="decimal" value={bws} onChange={(e) => setBws(e.target.value)} /></label>
          <button className="btn primary" onClick={() => apply(Number(speed))}>Apply as new condition</button>
        </div>
        )}
        {!controlled && (
          <p className="hint">Each change starts a new condition. The report summarises each condition separately.</p>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      <LiveGaitChart gait={g} />

      <LiveChart />

      <section className="panel">
        <h2>Recent steps</h2>
        <table className="recordings">
          <thead>
            <tr><th>Time</th><th>Foot</th><th>Step time</th><th>Step length</th><th>Stride length</th><th>Confidence</th></tr>
          </thead>
          <tbody>
            {[...session.recent_steps].reverse().map((s) => (
              <tr key={s.time_s} className={s.accepted ? "" : "muted"}>
                <td>{fmtNum(s.time_s, 1)} s</td>
                <td>{s.side === "L" ? "Left" : "Right"}</td>
                <td>{fmtNum(s.step_time_s, 3)} s</td>
                <td>{s.step_length_m === null ? "—" : `${fmtNum(s.step_length_m, 2)} m`}</td>
                <td>{s.stride_length_m === null ? "—" : `${fmtNum(s.stride_length_m, 2)} m`}</td>
                <td title={s.reasons.join("; ")}>{s.transition ? "speed change" : s.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2>End session</h2>
        <label className="wide">Closing notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        <HoldButton label={controlled ? "Hold to stop the belt and end the session" : "Hold to end session"}
          onConfirm={stop} />
        {controlled && <p className="hint">Ending the session stops the belt if it is still running.</p>}
      </section>
    </div>
  );
}

function Metric({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-unit">{unit}</div>
    </div>
  );
}

/** Ends only after a 1 s press, so a brushed screen cannot end a session. */
export function HoldButton({ label, onConfirm }: { label: string; onConfirm: () => void }) {
  const [progress, setProgress] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const begin = () => {
    const started = Date.now();
    timer.current = setInterval(() => {
      const p = Math.min(1, (Date.now() - started) / 1000);
      setProgress(p);
      if (p >= 1) {
        cancel();
        onConfirm();
      }
    }, 30);
  };
  const cancel = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    setProgress(0);
  };
  return (
    <button className="btn danger hold" onPointerDown={begin} onPointerUp={cancel} onPointerLeave={cancel}>
      <span className="hold-fill" style={{ width: `${progress * 100}%` }} />
      <span className="hold-label">{label}</span>
    </button>
  );
}
