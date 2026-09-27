export interface Series {
  name: string;
  colour: string;
  points: [number, number][];
  dots?: boolean;
}

interface Props {
  series: Series[];
  yLabel: string;
  xLabel?: string;
  markers?: { x: number; label: string }[];
  height?: number;
}

/** A static SVG chart for session reports. */
export function LineChart({ series, yLabel, xLabel = "time (s)", markers = [], height = 220 }: Props) {
  const all = series.flatMap((s) => s.points);
  if (all.length < 2) return <p className="muted">Not enough data to chart.</p>;
  const width = 1000;
  const left = 64;
  const bottom = 34;
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs, x0 + 1);
  let y0 = Math.min(...ys);
  let y1 = Math.max(...ys);
  const pad = Math.max((y1 - y0) * 0.1, Math.abs(y1) * 0.02, 0.01);
  y0 -= pad;
  y1 += pad;
  const x = (v: number) => left + ((v - x0) / (x1 - x0)) * (width - left - 12);
  const y = (v: number) => 10 + (1 - (v - y0) / (y1 - y0)) * (height - bottom - 10);
  const ticks = Array.from({ length: 5 }, (_, i) => y0 + ((y1 - y0) * i) / 4);
  const xticks = Array.from({ length: 6 }, (_, i) => x0 + ((x1 - x0) * i) / 5);
  const digits = y1 - y0 < 2 ? 2 : y1 - y0 < 20 ? 1 : 0;

  return (
    <div className="line-chart">
      <div className="legend">
        {series.map((s) => (
          <span key={s.name}><i style={{ background: s.colour }} />{s.name}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={yLabel}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={width - 12} y1={y(t)} y2={y(t)} className="grid" />
            <text x={left - 8} y={y(t) + 4} textAnchor="end">{t.toFixed(digits)}</text>
          </g>
        ))}
        {xticks.map((t) => (
          <text key={t} x={x(t)} y={height - 14} textAnchor="middle">{Math.round(t)}</text>
        ))}
        {markers.map((m) => (
          <g key={`${m.x}-${m.label}`}>
            <line x1={x(m.x)} x2={x(m.x)} y1={10} y2={height - bottom} className="marker" />
            <text x={x(m.x) + 4} y={22} className="marker-label">{m.label}</text>
          </g>
        ))}
        {series.map((s) =>
          s.dots ? (
            <g key={s.name} fill={s.colour}>
              {s.points.map(([px, py], i) => <circle key={i} cx={x(px)} cy={y(py)} r={3} />)}
            </g>
          ) : (
            <polyline key={s.name} fill="none" stroke={s.colour} strokeWidth={2}
              points={s.points.map(([px, py]) => `${x(px)},${y(py)}`).join(" ")} />
          ),
        )}
        <text x={14} y={height / 2} transform={`rotate(-90 14 ${height / 2})`} textAnchor="middle">{yLabel}</text>
        <text x={(width + left) / 2} y={height - 1} textAnchor="middle">{xLabel}</text>
      </svg>
    </div>
  );
}
