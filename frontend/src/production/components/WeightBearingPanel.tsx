import type { WeightBearing } from "../../types";

/**
 * What each leg is carrying, against what the surgeon allowed.
 *
 * This is the one number on the machine a patient physically cannot sense.
 * Told "no more than 20 kg on that leg", they put roughly half their body
 * weight through it and have no idea — compliance measured at 0% on the first
 * post-operative day. So it is shown large, in both kilograms and percent of
 * body weight, because percentage-based orders are followed noticeably better
 * than kilogram-based ones.
 *
 * Peak per step and the count of steps over the limit, never a session mean: a
 * patient can average under the limit while exceeding it on half their steps,
 * and the average hides exactly what this exists to catch.
 */
export function WeightBearingPanel({ wb, compact = false }: {
  wb: WeightBearing;
  compact?: boolean;
}) {
  if (wb.quality === "unavailable") {
    return (
      <div className="prod-wb">
        <div className="prod-eyebrow">Weight bearing</div>
        <div className="muted" style={{ fontSize: 13 }}>{wb.reason}</div>
      </div>
    );
  }

  const over = wb.limit_kg != null && wb.steps_over > 0;
  const pctOver = wb.steps ? (100 * wb.steps_over) / wb.steps : 0;

  return (
    <div className={`prod-wb${over ? " over" : ""}`}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <div className="prod-eyebrow" style={{ margin: 0 }}>Weight bearing</div>
        {wb.limit_kg != null && (
          <span className="prod-wb-limit">limit {wb.limit_kg} kg per leg</span>
        )}
        {wb.quality === "fair" && <span className="prod-wb-flag">approximate</span>}
      </div>

      {wb.quality === "combined" ? (
        <>
          <div className="prod-wb-legs">
            <Leg label="Both legs" kg={wb.combined_kg} pct={wb.combined_pct_bw}
                 limit={null} wide />
          </div>
          <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>{wb.reason}</p>
        </>
      ) : (
        <>
          <div className="prod-wb-legs">
            <Leg label="Left leg" kg={wb.left_kg} pct={wb.left_pct_bw} limit={wb.limit_kg} />
            <Leg label="Right leg" kg={wb.right_kg} pct={wb.right_pct_bw} limit={wb.limit_kg} />
          </div>
          {wb.reason && (
            <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>{wb.reason}</p>
          )}
        </>
      )}

      {wb.limit_kg != null && wb.steps > 0 && (
        <div className={`prod-wb-steps${over ? " over" : ""}`}>
          {wb.steps_over === 0
            ? `All ${wb.steps} steps within the limit`
            : `${wb.steps_over} of ${wb.steps} steps over the limit (${pctOver.toFixed(0)}%)`}
        </div>
      )}

      {!compact && wb.body_weight_kg == null && (
        <p className="muted" style={{ fontSize: 11.5, margin: "8px 0 0" }}>
          No body weight on record, so percentages are unavailable. Kilograms are unaffected.
        </p>
      )}
    </div>
  );
}

function Leg({ label, kg, pct, limit, wide = false }: {
  label: string;
  kg: number | null;
  pct: number | null;
  limit: number | null;
  wide?: boolean;
}) {
  const over = limit != null && kg != null && kg > limit;
  const frac = limit && kg ? Math.min(1.4, kg / limit) : null;
  return (
    <div className={`prod-wb-leg${over ? " over" : ""}${wide ? " wide" : ""}`}>
      <div className="l">{label}</div>
      <div className="kg">{kg == null ? "—" : `${kg.toFixed(1)}`}<span>kg</span></div>
      <div className="pct">{pct == null ? " " : `${pct.toFixed(0)}% body weight`}</div>
      {frac != null && (
        <div className="bar"><i style={{ width: `${Math.min(100, frac * 100 / 1.4)}%` }} /></div>
      )}
      {limit != null && (
        <div className="verdict">{over ? "over the limit" : "within limit"}</div>
      )}
    </div>
  );
}
