import type { SessionReport, SessionSummary } from "../../types";

/**
 * Weight bearing, after the session.
 *
 * The live panel answers "am I over the limit right now". This answers the
 * question that goes in the patient's notes: across the whole session, how
 * hard did each leg work and how often was the prescription broken.
 *
 * Peak and worst-case, not averages — a patient can average under a limit
 * while exceeding it on half their steps.
 */
export function WeightBearingReport({ summary, meta }: {
  summary: SessionSummary | null;
  meta: SessionReport["meta"];
}) {
  const wb = summary?.weight_bearing;
  if (!wb || !wb.session || wb.session.steps === 0) return null;

  const s = wb.session;
  const bw = meta.details.body_weight_kg ?? wb.body_weight_kg ?? null;
  const limit = wb.limit_kg ?? meta.details.weight_bearing_limit_kg ?? null;
  const pctOver = s.steps ? (100 * s.steps_over) / s.steps : 0;
  const separable = wb.quality === "good" || wb.quality === "fair";

  const asPct = (kg: number | null) =>
    kg != null && bw ? ` · ${Math.round((100 * kg) / bw)}% BW` : "";

  return (
    <div className="prod-card">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <div className="prod-eyebrow" style={{ margin: 0 }}>Weight bearing</div>
        {limit != null && <span className="muted" style={{ fontSize: 12.5 }}>limit {limit} kg per leg</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                    gap: 18, marginTop: 14 }}>
        {separable ? (
          <>
            <Figure label="Left leg, typical peak"
              value={s.left_median_kg != null ? `${s.left_median_kg.toFixed(1)} kg` : "—"}
              note={`worst ${s.left_max_kg?.toFixed(1) ?? "—"} kg${asPct(s.left_median_kg)}`} />
            <Figure label="Right leg, typical peak"
              value={s.right_median_kg != null ? `${s.right_median_kg.toFixed(1)} kg` : "—"}
              note={`worst ${s.right_max_kg?.toFixed(1) ?? "—"} kg${asPct(s.right_median_kg)}`} />
          </>
        ) : (
          <Figure label="Both legs, worst step"
            value={s.combined_max_kg != null ? `${s.combined_max_kg.toFixed(1)} kg` : "—"}
            note="the legs could not be separated" />
        )}
        <Figure label="Steps" value={String(s.steps)} />
        {limit != null && (
          <Figure label="Over the limit"
            value={`${s.steps_over}`}
            note={`${pctOver.toFixed(0)}% of steps`}
            alarm={s.steps_over > 0} />
        )}
      </div>

      {wb.reason && (
        <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>{wb.reason}</p>
      )}
      {limit == null && (
        <p className="muted" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
          No weight-bearing limit was set for this session, so nothing is judged against one.
        </p>
      )}
    </div>
  );
}

function Figure({ label, value, note, alarm = false }: {
  label: string; value: string; note?: string; alarm?: boolean;
}) {
  return (
    <div>
      <div style={{ fontSize: 23, fontWeight: 700, color: alarm ? "var(--danger, #ff6378)" : undefined }}>
        {value}
      </div>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      {note && <div className="muted" style={{ fontSize: 11, opacity: .75 }}>{note}</div>}
    </div>
  );
}
