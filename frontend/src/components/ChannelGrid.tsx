import { fmtInt } from "../format";
import type { Channel } from "../types";

const POSITIONS: Record<Channel["name"], string> = {
  TL: "Top-left",
  TR: "Top-right",
  BR: "Bottom-right",
  BL: "Bottom-left",
};

// Laid out as the cells sit on the deck, so a press on a corner lights the tile in
// the same place.
const DECK_ORDER: Channel["name"][] = ["TL", "TR", "BL", "BR"];

interface Props {
  channels: Channel[];
  zero: Partial<Record<Channel["name"], number>>;
  onZero: () => void;
  onClearZero: () => void;
}

export function ChannelGrid({ channels, zero, onZero, onClearZero }: Props) {
  const byName = new Map(channels.map((c) => [c.name, c]));
  const hasZero = Object.keys(zero).length > 0;
  const deltas = DECK_ORDER.map((name) => {
    const c = byName.get(name);
    const z = zero[name];
    return c?.mean != null && z != null ? c.mean - z : null;
  });
  const largest = Math.max(1, ...deltas.map((d) => (d === null ? 0 : Math.abs(d))));

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Load cells</h2>
        <div className="actions">
          <button className="btn" onClick={onZero}>Zero all</button>
          {hasZero && <button className="btn ghost" onClick={onClearZero}>Clear zero</button>}
        </div>
      </div>
      <p className="hint">
        {hasZero
          ? "Press one corner at a time: the tile in the same place should respond most."
          : "With the deck empty, tap Zero all, then press each corner in turn."}
      </p>
      <div className="deck">
        {DECK_ORDER.map((name, i) => {
          const c = byName.get(name);
          const delta = deltas[i];
          const activity = delta === null ? 0 : Math.abs(delta) / largest;
          return (
            <article
              key={name}
              className={`cell${activity > 0.6 && Math.abs(delta ?? 0) > 5 * (c?.noise ?? 0) + 50 ? " active" : ""}`}
              data-testid={`cell-${name}`}
            >
              <header>
                <span className="cell-name">{name}</span>
                <span className="cell-pos">{POSITIONS[name]}</span>
              </header>
              <div className="cell-value" aria-label={`${name} raw value`}>{fmtInt(c?.last)}</div>
              <div className="cell-sub">
                {hasZero ? (
                  <>Change from zero <strong>{delta === null ? "—" : (delta >= 0 ? "+" : "") + fmtInt(delta)}</strong></>
                ) : (
                  <>1 s mean {fmtInt(c?.mean)}</>
                )}
              </div>
              <div className="bar" aria-hidden="true"><span style={{ width: `${activity * 100}%` }} /></div>
              <dl className="cell-stats">
                <div><dt>Noise</dt><dd>{fmtInt(c?.noise)}</dd></div>
                <div><dt>Min</dt><dd>{fmtInt(c?.min)}</dd></div>
                <div><dt>Max</dt><dd>{fmtInt(c?.max)}</dd></div>
              </dl>
            </article>
          );
        })}
      </div>
    </section>
  );
}
