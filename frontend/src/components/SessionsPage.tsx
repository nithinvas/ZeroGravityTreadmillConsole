import { useCallback, useEffect, useState } from "react";
import { getJson } from "../api";
import { fmtDuration, fmtInt, fmtNum } from "../format";
import type { SessionReport, SessionRow, Spread } from "../types";
import { CELL_COLOURS } from "./LiveChart";
import { LineChart } from "./LineChart";

export function SessionsPage({ openId, onOpen }: { openId: string | null; onOpen: (id: string | null) => void }) {
  if (openId) return <ReportView id={openId} onBack={() => onOpen(null)} />;
  return <SessionSearch onOpen={onOpen} />;
}

function SessionSearch({ onOpen }: { onOpen: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const search = useCallback(async () => {
    const params = new URLSearchParams({ q });
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    try {
      setRows(await getJson<SessionRow[]>(`/api/sessions?${params}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [q, from, to]);

  useEffect(() => {
    const timer = setTimeout(() => void search(), 250);
    return () => clearTimeout(timer);
  }, [search]);

  return (
    <section className="panel">
      <h2>Saved sessions</h2>
      <div className="search-bar">
        <input
          className="grow"
          placeholder="Search by patient name, ID, tester, issue or notes"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search sessions"
        />
        <label>From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>To<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      {error && <p className="error">{error}</p>}
      {rows && rows.length === 0 && <p className="muted">No sessions match.</p>}
      {rows && rows.length > 0 && (
        <div className="table-scroll">
          <table className="recordings clickable">
            <thead>
              <tr>
                <th>Date</th><th>Patient</th><th>ID</th><th>Tester</th><th>Speeds (km/h)</th><th>Length</th>
                <th>Cadence</th><th>Step length</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} onClick={() => onOpen(r.id)} tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && onOpen(r.id)}>
                  <td>{localTime(r.started_at)}</td>
                  <td>{r.patient_name || "—"}</td>
                  <td>{r.patient_id || "—"}</td>
                  <td>{r.tester || "—"}</td>
                  <td>{r.speeds || "—"}</td>
                  <td>{fmtDuration(r.duration_s)}</td>
                  <td>{r.main_cadence ? `${fmtNum(r.main_cadence, 1)} /min` : "—"}</td>
                  <td>{r.main_step_length ? `${fmtNum(r.main_step_length, 2)} m` : "—"}</td>
                  <td>{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="hint">Cadence and step length here are from each session's longest condition.</p>
    </section>
  );
}

function ReportView({ id, onBack }: { id: string; onBack: () => void }) {
  const [report, setReport] = useState<SessionReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<SessionReport>(`/api/sessions/${encodeURIComponent(id)}`).then(setReport, (e: Error) => setError(e.message));
  }, [id]);

  if (error) return <section className="panel"><p className="error">{error}</p><button className="btn" onClick={onBack}>Back</button></section>;
  if (!report) return <section className="panel"><p className="muted">Loading report…</p></section>;

  const { meta, summary, steps, trace } = report;
  const d = meta.details;
  const accepted = steps.filter((s) => s.accepted);
  const markers = meta.conditions.map((c) => ({
    x: c.start_s,
    label: c.speed_kph === null ? "belt stopped" : `${c.speed_kph} km/h`,
  }));
  const file = (name: string) => `/api/sessions/${encodeURIComponent(id)}/files/${name}`;

  return (
    <div className="stack report">
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{d.patient_name || d.patient_id}{d.patient_id && d.patient_name ? ` · ${d.patient_id}` : ""}</h2>
            <p className="muted">{localTime(meta.started_at)} · {meta.status} · session {meta.id}</p>
          </div>
          <button className="btn" onClick={onBack}>Back to sessions</button>
        </div>
        <dl className="details">
          <Detail label="Tester" value={d.tester} />
          <Detail label="Issue" value={d.issue} />
          <Detail label="Activity" value={d.activity} />
          <Detail label="Body weight" value={d.body_weight_kg ? `${d.body_weight_kg} kg` : ""} />
          <Detail label="Body-weight support" value={d.bws_percent !== null ? `${d.bws_percent}%` : ""} />
          <Detail label="Duration" value={fmtDuration(meta.duration_s)} />
          <Detail label="Walking time" value={summary ? fmtDuration(summary.walking_s) : ""} />
          <Detail label="Distance" value={summary ? `${fmtNum(summary.distance_m, 1)} m` : ""} />
          <Detail label="Steps accepted" value={summary ? `${summary.steps_accepted} of ${summary.steps_total}` : ""} />
          <Detail label="Coefficients" value={`${meta.calibration.method.replaceAll("_", " ")} · ${meta.calibration.counts_per_kg.map((c) => fmtNum(c, 0)).join(" / ")} counts/kg`} />
          <Detail label="Software" value={`${meta.gait_engine.version} · app ${meta.app_version}`} />
          <Detail label="Notes" value={[d.notes, meta.closing_notes].filter(Boolean).join(" — ")} />
        </dl>
        <div className="actions">
          {["steps.csv", "trace.csv", "summary.json", "session.json"].map((n) => (
            <a key={n} className="btn ghost" href={file(n)} download>{n}</a>
          ))}
        </div>
      </section>

      {summary && (
        <section className="panel">
          <h2>By condition</h2>
          <p className="hint">Median, with the interquartile range in brackets, from accepted steps only. Steps during a speed change are excluded.</p>
          <div className="table-scroll">
            <table className="recordings">
              <thead>
                <tr><th>#</th><th>Speed</th><th>Incline</th><th>Activity</th><th>BWS</th><th>Steps</th><th>Cadence (/min)</th><th>Step length (m)</th><th>Stride length (m)</th></tr>
              </thead>
              <tbody>
                {summary.blocks.map((b) => (
                  <tr key={b.condition.id}>
                    <td>{b.condition.id}</td>
                    <td>{b.condition.speed_kph === null ? "belt stopped" : `${b.condition.speed_kph} km/h`}</td>
                    <td>{b.condition.incline_percent === null ? "—" : `${b.condition.incline_percent}%`}</td>
                    <td>{b.condition.activity}</td>
                    <td>{b.condition.bws_percent !== null ? `${b.condition.bws_percent}%` : "—"}</td>
                    <td>{b.steps_accepted} / {b.steps_total}</td>
                    <td>{spread(b.cadence_spm, 1)}</td>
                    <td>{spread(b.step_length_m, 2)}</td>
                    <td>{spread(b.stride_length_m, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel">
        <h2>Cadence</h2>
        <LineChart yLabel="steps/min" markers={markers} series={[{
          name: "per stride", colour: "#4cc2ff", dots: true,
          points: accepted.filter((s) => s.stride_time_s).map((s) => [s.time_s, 120 / s.stride_time_s!] as [number, number]),
        }]} />
      </section>

      <section className="panel">
        <h2>Step length</h2>
        <LineChart yLabel="m" markers={markers} series={[
          { name: "left foot landing", colour: "#4cc2ff", dots: true,
            points: accepted.filter((s) => s.side === "L" && s.step_length_m !== null).map((s) => [s.time_s, s.step_length_m!] as [number, number]) },
          { name: "right foot landing", colour: "#f5b041", dots: true,
            points: accepted.filter((s) => s.side === "R" && s.step_length_m !== null).map((s) => [s.time_s, s.step_length_m!] as [number, number]) },
        ]} />
      </section>

      <section className="panel">
        <h2>Load</h2>
        <LineChart yLabel="kg" markers={markers} series={[
          { name: "total", colour: "#e8edf3", points: zip(trace.time_s, trace.total_kg) },
          { name: "TL", colour: CELL_COLOURS[0], points: zip(trace.time_s, trace.tl_kg) },
          { name: "TR", colour: CELL_COLOURS[1], points: zip(trace.time_s, trace.tr_kg) },
          { name: "BR", colour: CELL_COLOURS[2], points: zip(trace.time_s, trace.br_kg) },
          { name: "BL", colour: CELL_COLOURS[3], points: zip(trace.time_s, trace.bl_kg) },
        ]} height={260} />
      </section>

      <section className="panel">
        <h2>Steps <span className="muted">· {fmtInt(steps.length)} detected</span></h2>
        <div className="table-scroll tall">
          <table className="recordings">
            <thead>
              <tr><th>Time</th><th>Foot</th><th>Step time</th><th>Step length</th><th>Stride length</th><th>Speed</th><th>Confidence</th><th>Notes</th></tr>
            </thead>
            <tbody>
              {steps.slice(0, 500).map((s) => (
                <tr key={s.time_s} className={s.accepted ? "" : "muted"}>
                  <td>{fmtNum(s.time_s, 1)} s</td>
                  <td>{s.side === "L" ? "Left" : "Right"}</td>
                  <td>{fmtNum(s.step_time_s, 3)} s</td>
                  <td>{s.step_length_m === null ? "—" : fmtNum(s.step_length_m, 2)}</td>
                  <td>{s.stride_length_m === null ? "—" : fmtNum(s.stride_length_m, 2)}</td>
                  <td>{s.speed_kph ?? "—"}</td>
                  <td>{s.confidence}</td>
                  <td>{s.reasons.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {steps.length > 500 && <p className="hint">First 500 of {steps.length} steps shown; download steps.csv for all of them.</p>}
      </section>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function spread(s: Spread, digits: number): string {
  if (s.median === null) return "—";
  const m = fmtNum(s.median, digits);
  return s.q1 !== null && s.q3 !== null ? `${m} (${fmtNum(s.q1, digits)}–${fmtNum(s.q3, digits)})` : m;
}

function zip(xs: number[], ys: number[]): [number, number][] {
  return xs.map((x, i) => [x, ys[i]]);
}

function localTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
