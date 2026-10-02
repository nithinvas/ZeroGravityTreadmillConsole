import { useEffect, useState } from "react";
import { getJson } from "../api";
import { LineChart } from "../components/LineChart";
import { CELL_COLOURS } from "../components/LiveChart";
import { fmtDuration, fmtNum } from "../format";
import type { SessionReport, Spread } from "../types";
import { FootForceChart } from "./components/FootForceChart";

/**
 * What the therapist reads afterwards, and what goes in the patient's file.
 *
 * The score at the top is a summary, not a measurement — it is spelled out
 * underneath so nobody treats an orange 74 as a diagnosis.
 */
export function ReportScreen({ id, onDone }: { id: string; onDone: () => void }) {
  const [report, setReport] = useState<SessionReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<SessionReport>(`/api/sessions/${encodeURIComponent(id)}`)
      .then(setReport, (e: Error) => setError(e.message));
  }, [id]);

  if (error) return <div className="prod-empty"><div className="prod-error">{error}</div></div>;
  if (!report) return <div className="prod-empty">Loading the report…</div>;

  const { meta, summary, steps, trace } = report;
  const accepted = steps.filter((s) => s.accepted);
  const markers = meta.conditions.map((c) => ({
    x: c.start_s,
    label: c.speed_kph === null ? "stopped" : `${c.speed_kph} km/h`,
  }));
  const file = (name: string) => `/api/sessions/${encodeURIComponent(id)}/files/${name}`;

  const cadence = accepted.filter((s) => s.stride_time_s)
    .map((s) => [s.time_s, 120 / (s.stride_time_s as number)] as [number, number]);
  const stepLength = accepted.filter((s) => s.step_length_m !== null)
    .map((s) => [s.time_s, s.step_length_m as number] as [number, number]);

  const score = gaitScore(summary?.blocks?.[0]?.cadence_spm, summary?.steps_accepted, summary?.steps_total);

  return (
    <div className="prod-report">
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <h2 style={{ margin: 0 }}>{meta.details.patient_name || meta.details.patient_id}</h2>
          <div className="muted" style={{ fontSize: 13 }}>
            <span className="mono">{meta.details.patient_id}</span> · {localTime(meta.started_at)} · {meta.status}
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <a className="prod-btn ghost" href={file("steps.csv")} download>steps.csv</a>
          <a className="prod-btn ghost" href={file("trace.csv")} download>trace.csv</a>
          <button className="prod-btn primary" onClick={onDone}>Done</button>
        </div>
      </div>

      <div className="prod-summary">
        <Tile label="Duration" value={fmtDuration(meta.duration_s)} />
        <Tile label="Walking" value={summary ? fmtDuration(summary.walking_s) : "—"} />
        <Tile label="Distance" value={summary ? `${fmtNum(summary.distance_m, 1)} m` : "—"} />
        <Tile label="Steps" value={summary ? `${summary.steps_accepted} / ${summary.steps_total}` : "—"} />
        <Tile label="Offloading" value={meta.details.bws_percent !== null ? `${meta.details.bws_percent}%` : "—"} tone="warn" />
        <Tile label="Deck height" value={meta.height_mm ? `${meta.height_mm} mm` : "—"} />
      </div>

      <div className="prod-two">
        <div className="prod-card prod-score">
          <div className="prod-eyebrow">Gait quality</div>
          <div className="n">{score === null ? "—" : score}</div>
          <div className="prod-progress" style={{ marginTop: 10 }}>
            <span style={{ width: `${score ?? 0}%`, background: "var(--warn)" }} />
          </div>
          <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
            A summary of how much of the walk the engine could measure confidently, not a
            clinical assessment. The numbers it is built from are below.
          </p>
        </div>
        <div className="prod-card">
          <div className="prod-eyebrow">Per condition</div>
          <dl className="prod-dl">
            {summary?.blocks.map((b) => (
              <div key={b.condition.id}>
                <dt>
                  {b.condition.speed_kph === null ? "Belt stopped" : `${b.condition.speed_kph} km/h`}
                  {" "}· {b.steps_accepted} steps
                </dt>
                <dd>
                  {spread(b.cadence_spm, 1)} /min · {spread(b.step_length_m, 2)} m
                </dd>
              </div>
            ))}
            {!summary?.blocks.length && <div><dt>No steps were recorded.</dt><dd /></div>}
          </dl>
        </div>
      </div>

      <div className="prod-card">
        <div className="prod-eyebrow">Cadence</div>
        <LineChart yLabel="steps/min" markers={markers}
          series={[{ name: "per stride", colour: "#4cc2ff", dots: true, points: cadence }]} />
      </div>

      <div className="prod-card">
        <div className="prod-eyebrow">Step length</div>
        <LineChart yLabel="m" markers={markers}
          series={[{ name: "per step", colour: "#19e5a5", dots: true, points: stepLength }]} />
      </div>

      <FeetCard report={report} />

      <div className="prod-card">
        <div className="prod-eyebrow">Load on the deck</div>
        <LineChart yLabel="kg" markers={markers} height={240} series={[
          { name: "total", colour: "#e8f0f7", points: zip(trace.time_s, trace.total_kg) },
          { name: "TL", colour: CELL_COLOURS[0], points: zip(trace.time_s, trace.tl_kg) },
          { name: "TR", colour: CELL_COLOURS[1], points: zip(trace.time_s, trace.tr_kg) },
          { name: "BR", colour: CELL_COLOURS[2], points: zip(trace.time_s, trace.br_kg) },
          { name: "BL", colour: CELL_COLOURS[3], points: zip(trace.time_s, trace.bl_kg) },
        ]} />
      </div>
    </div>
  );
}

function Tile({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="prod-tile">
      <div className="n" style={tone === "warn" ? { color: "var(--warn)" } : undefined}>{value}</div>
      <div className="l">{label}</div>
    </div>
  );
}

/**
 * A single number for the top of the report: what fraction of detected steps the
 * engine was confident about. Deliberately simple and deliberately explained —
 * an unexplained score invites being read as a clinical result.
 */
function gaitScore(_cadence: Spread | undefined, accepted?: number, total?: number): number | null {
  if (!total) return null;
  return Math.round(((accepted ?? 0) / total) * 100);
}

function spread(s: Spread, digits: number): string {
  return s.median === null ? "—" : fmtNum(s.median, digits);
}

function zip(xs: number[], ys: number[]): [number, number][] {
  return xs.map((x, i) => [x, ys[i]]);
}

function localTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}


/**
 * Per-foot load across the whole session.
 *
 * These are the same curves that were on the screen during the session -- the
 * console wrote down what it computed live rather than recomputing it here, so
 * the record cannot disagree with what the therapist watched.
 */
function FeetCard({ report }: { report: SessionReport }) {
  const feet = report.feet;
  if (!feet || feet.t.length < 2) return null;

  const points = feet.t.map((t, i) => ({ t, left: feet.left[i], right: feet.right[i] }));
  const resolved = points.filter((p) => p.left !== null);
  // Mean total load over the session is the weight the deck actually carried,
  // which is the right reference even when body-weight support took some of it.
  const bw = Math.max(1, Math.round(
    feet.total.reduce((a, b) => a + b, 0) / Math.max(1, feet.total.length)));

  const peak = (side: "left" | "right") =>
    resolved.reduce((m, p) => Math.max(m, p[side] ?? 0), 0);
  const pl = peak("left");
  const pr = peak("right");
  const asym = pl + pr > 0 ? (200 * Math.abs(pl - pr)) / (pl + pr) : 0;

  return (
    <div className="prod-card">
      <div className="prod-eyebrow">Left / right load</div>
      <FootForceChart points={points} bodyWeightKg={bw} height={260} showAll />
      <div style={{ display: "flex", gap: 26, marginTop: 14, flexWrap: "wrap" }}>
        <Figure label="Peak, left" value={`${pl.toFixed(1)} kg`} />
        <Figure label="Peak, right" value={`${pr.toFixed(1)} kg`} />
        <Figure label="Difference" value={`${asym.toFixed(1)}%`} />
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
        Estimated by splitting one deck between two feet, not measured with two
        force plates. Gaps are moments that could not be resolved.
      </p>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
    </div>
  );
}
