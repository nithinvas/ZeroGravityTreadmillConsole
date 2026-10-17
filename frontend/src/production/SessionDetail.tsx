import { useEffect, useMemo, useState } from "react";
import { getJson } from "../api";
import { fmtDuration } from "../format";
import type { SessionReport } from "../types";
import { ZoomBar, ZoomChart, type Range, type Series } from "./components/ZoomChart";

/**
 * One past session, in full.
 *
 * Three things a therapist asks of an old session, in order: how did it go,
 * what did each corner of the deck see, and what was each foot carrying. The
 * numbers answer the first; the charts answer the other two, and they share a
 * zoom so a moment picked out on one is the same moment on all of them.
 *
 * Load cells are drawn one per chart rather than four on shared axes. Stacked
 * together they overlap into a thicket -- which is fine for spotting that the
 * deck is loaded, and useless for spotting that one corner has stopped
 * responding.
 */

const CELLS = [
  { key: "tl_kg", name: "Top left", colour: "#38bdf8" },
  { key: "tr_kg", name: "Top right", colour: "#fbbf24" },
  { key: "br_kg", name: "Bottom right", colour: "#fb7185" },
  { key: "bl_kg", name: "Bottom left", colour: "#a78bfa" },
] as const;

export function SessionDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [report, setReport] = useState<SessionReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<Range | null>(null);
  const [tab, setTab] = useState<"cells" | "feet">("cells");

  useEffect(() => {
    getJson<SessionReport>(`/api/sessions/${encodeURIComponent(id)}`)
      .then(setReport, (e: Error) => setError(e.message));
  }, [id]);

  const bounds = useMemo<Range>(() => {
    const t = report?.trace?.time_s ?? [];
    return { lo: t[0] ?? 0, hi: t[t.length - 1] ?? 1 };
  }, [report]);

  useEffect(() => { if (report) setRange({ ...bounds }); }, [report, bounds]);

  if (error) return <div className="prod-error" role="alert">{error}</div>;
  if (!report || !range) return <div className="prod-empty">Loading…</div>;

  const m = report.meta;
  const s = report.summary;
  const main = s?.blocks?.[0];
  const steps = report.steps ?? [];
  const left = steps.filter((x) => x.side === "L").length;
  const right = steps.filter((x) => x.side === "R").length;
  const symmetry = left + right > 0 ? (200 * Math.abs(left - right)) / (left + right) : 0;
  const peak = Math.max(0, ...(report.trace?.total_kg ?? [0]));

  const cellSeries = (key: string): Series[] => {
    const t = report.trace.time_s;
    const v = (report.trace as unknown as Record<string, number[]>)[key];
    return [{ name: key, colour: CELLS.find((c) => c.key === key)!.colour,
              points: t.map((x, i) => [x, v[i] ?? null] as [number, number | null]) }];
  };

  const feet = report.feet;
  const feetSeries: Series[] = feet?.t?.length
    ? [
        { name: "left", colour: "#38bdf8", points: feet.t.map((x, i) => [x, feet.left[i]] as [number, number | null]) },
        { name: "right", colour: "#fb7185", points: feet.t.map((x, i) => [x, feet.right[i]] as [number, number | null]) },
      ]
    : [];

  return (
    <div style={{ padding: 22, maxWidth: 1180, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0 }}>{m.details.patient_name}</h2>
          <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>
            {new Date(m.started_at).toLocaleString()} · {fmtDuration(m.duration_s)}
            {m.details.issue ? ` · ${m.details.issue}` : ""}
            {m.details.tester ? ` · run by ${m.details.tester}` : " · therapist not recorded"}
          </p>
        </div>
        <button className="prod-btn ghost" style={{ marginLeft: "auto" }} onClick={onBack}>Back</button>
      </div>

      <div className="prod-card">
        <div className="prod-eyebrow">Session insights</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(132px, 1fr))", gap: 16 }}>
          <Stat label="Duration" value={fmtDuration(m.duration_s)} />
          <Stat label="Walking time" value={fmtDuration(s?.walking_s ?? 0)} />
          <Stat label="Distance" value={`${(s?.distance_m ?? 0).toFixed(1)} m`} />
          <Stat label="Steps" value={`${s?.steps_accepted ?? 0}`} note={`of ${s?.steps_total ?? 0} detected`} />
          <Stat label="Left / right" value={`${left} / ${right}`} note={`${symmetry.toFixed(1)}% apart`} />
          <Stat label="Avg cadence" value={fmtNum(main?.cadence_spm?.median)} note="steps/min" />
          <Stat label="Avg step length" value={fmtNum(main?.step_length_m?.median, 3)} note="m" />
          <Stat label="Avg stride length" value={fmtNum(main?.stride_length_m?.median, 3)} note="m" />
          <Stat label="Avg step time" value={fmtNum(main?.step_time_s?.median, 3)} note="s" />
          <Stat label="Peak deck load" value={`${peak.toFixed(1)} kg`} />
          <Stat label="Body weight" value={`${m.details.body_weight_kg ?? "—"} kg`} note="as entered" />
          <Stat label="Offloading" value={m.details.bws_percent != null ? `${m.details.bws_percent}%` : "—"}
                note="set, not measured" />
        </div>
        {(main?.low_confidence ?? 0) > 0 && (
          <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 12 }}>
            {main?.low_confidence} steps were graded low confidence and are excluded from the averages.
          </p>
        )}
      </div>

      <div className="prod-tabs" style={{ marginTop: 18 }}>
        <button className={`prod-tab${tab === "cells" ? " on" : ""}`} onClick={() => setTab("cells")}>
          Load cells
        </button>
        <button className={`prod-tab${tab === "feet" ? " on" : ""}`} onClick={() => setTab("feet")}>
          Left / right load
        </button>
      </div>

      <div className="prod-card" style={{ marginTop: 14 }}>
        <ZoomBar range={range} bounds={bounds} onRange={setRange} />

        {tab === "cells" && (
          <>
            <ZoomChart series={[{ name: "total", colour: "#e8f0f7",
                points: report.trace.time_s.map((x, i) => [x, report.trace.total_kg[i]] as [number, number | null]) }]}
              range={range} onRange={setRange} bounds={bounds} yLabel="total kg" height={140} zeroLine />
            {CELLS.map((c) => (
              <div key={c.key} style={{ marginTop: 10 }}>
                <div className="muted" style={{ fontSize: 12, color: c.colour, marginBottom: 2 }}>{c.name}</div>
                <ZoomChart series={cellSeries(c.key)} range={range} onRange={setRange}
                  bounds={bounds} yLabel="kg" height={120} zeroLine />
              </div>
            ))}
            <p className="muted" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
              One chart per corner, all on the same time axis — zoom one and they all follow.
            </p>
          </>
        )}

        {tab === "feet" && (
          feetSeries.length ? (
            <>
              <ZoomChart series={feetSeries} range={range} onRange={setRange}
                bounds={bounds} yLabel="kg" height={260} zeroLine />
              <div style={{ display: "flex", gap: 18, fontSize: 12, color: "var(--muted,#7e8fa0)", marginTop: 6 }}>
                <Key colour="#38bdf8" label="Left foot" />
                <Key colour="#fb7185" label="Right foot" />
              </div>
              <p className="muted" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
                Estimated by splitting one deck between two feet, not measured with two force plates.
                Breaks in a line are moments that could not be resolved. This estimate is still being
                validated — read the shape, not the exact split.
              </p>
            </>
          ) : (
            <div className="prod-empty">
              No per-foot curves were recorded for this session.
              <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                Sessions recorded before this feature existed only have the four load cells.
              </div>
            </div>
          )
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <div style={{ fontSize: 21, fontWeight: 700, lineHeight: 1.15 }}>{value}</div>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      {note && <div className="muted" style={{ fontSize: 11, opacity: .75 }}>{note}</div>}
    </div>
  );
}

function Key({ colour, label }: { colour: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <i style={{ width: 14, height: 2.5, background: colour, borderRadius: 2, display: "inline-block" }} />
      {label}
    </span>
  );
}

function fmtNum(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : v.toFixed(digits);
}
