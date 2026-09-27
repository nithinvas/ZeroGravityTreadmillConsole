import { fmtInt, fmtNum } from "../format";
import type { Snapshot } from "../types";

const DECK: { name: string; index: number; label: string }[] = [
  { name: "TL", index: 0, label: "Top-left" },
  { name: "TR", index: 1, label: "Top-right" },
  { name: "BL", index: 3, label: "Bottom-left" },
  { name: "BR", index: 2, label: "Bottom-right" },
];

const METHOD_TEXT: Record<string, string> = {
  manual: "Manual coefficients",
  defaults: "Default tested values",
  one_capture: "Known weight, one capture",
  four_position: "Known weight, four corners",
  four_position_shared: "Known weight, four corners (shared coefficient)",
};

export function WeightPage({ snapshot, onCalibrate }: { snapshot: Snapshot; onCalibrate: () => void }) {
  const { calibration, weight } = snapshot;

  if (calibration.status === "missing" || weight === null) {
    return (
      <section className="panel empty-state">
        <h2>Measure weight</h2>
        <p>{calibration.message || "Waiting for readings from the board."}</p>
        {calibration.status === "missing" && (
          <button className="btn primary" onClick={onCalibrate}>Calibrate or enter coefficients</button>
        )}
      </section>
    );
  }

  return (
    <div className="stack">
      {calibration.status === "firmware_mismatch" && (
        <div className="warning severe" role="alert">
          <span className="warning-icon" aria-hidden="true">!</span>
          <span>{calibration.message}</span>
        </div>
      )}
      <section className="panel weight-hero">
        <h2>Live weight</h2>
        <div className="weight-value" data-testid="live-weight">
          {fmtNum(weight.live_kg, 2)} <span>kg</span>
        </div>
        <div className="weight-average">
          2-second average <strong>{fmtNum(weight.average_kg, 2)} kg</strong>
        </div>
        <div className={`badge ${weight.stable ? "badge-ok" : "badge-wait"}`}>
          {weight.stable ? "Stable reading" : "Settling…"}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Per-cell load</h2>
          <button className="btn ghost" onClick={onCalibrate}>Recalibrate</button>
        </div>
        <div className="deck compact">
          {DECK.map(({ name, index, label }) => (
            <article key={name} className="cell">
              <header>
                <span className="cell-name">{name}</span>
                <span className="cell-pos">{label}</span>
              </header>
              <div className="cell-value small">{fmtNum(weight.cells_kg[index], 2)} kg</div>
              <div className="cell-sub">raw {fmtInt(weight.raw[index])}</div>
            </article>
          ))}
        </div>
        <p className="hint">
          Calibration: {METHOD_TEXT[calibration.method ?? ""] ?? calibration.method}. The deck weight is the sum
          of the four cells, so it is the same wherever the load stands; the per-cell split depends on position.
        </p>
      </section>
    </div>
  );
}
