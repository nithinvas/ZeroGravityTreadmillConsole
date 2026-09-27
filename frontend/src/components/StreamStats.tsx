import { fmtDuration, fmtInt, fmtNum } from "../format";
import type { Snapshot } from "../types";

export function StreamStats({ snapshot }: { snapshot: Snapshot }) {
  const { stream, app } = snapshot;
  const c = stream.counters;
  const items: [string, string, string?][] = [
    ["Samples/s per channel", fmtNum(stream.rate_hz, 2), `nominal ${fmtNum(app.nominal_rate_hz, 2)}`],
    ["USB packets/s", fmtNum(stream.packets_per_s, 2)],
    ["Streaming for", fmtDuration(stream.elapsed_s)],
    ["Samples", fmtInt(c.samples)],
    ["Short transfers", fmtInt(c.short_transfers)],
    ["Out of range", fmtInt(c.out_of_range)],
    ["Timeouts", fmtInt(c.timeouts)],
    ["Reconnects", fmtInt(c.reconnects)],
    ["Queue overflows", fmtInt(c.queue_overflows)],
    ["Sample period", `${fmtNum(stream.sample_period_us, 1)} µs`],
  ];
  return (
    <section className="panel">
      <h2>Stream</h2>
      <dl className="stats">
        {items.map(([label, value, note]) => (
          <div key={label} className="stat">
            <dt>{label}</dt>
            <dd>{value}</dd>
            {note && <small>{note}</small>}
          </div>
        ))}
      </dl>
    </section>
  );
}
