import { useCallback, useEffect, useRef, useState } from "react";
import { useSocket } from "../useSocket";

// [seq, t_s, TL, TR, BR, BL, total]
type Point = number[];

export const CELL_COLOURS = ["#4cc2ff", "#f5b041", "#3ecf8e", "#c77dff"];
const CELL_NAMES = ["TL", "TR", "BR", "BL"];

/**
 * Live load charts fed by /ws/chart (25 points a second, block-averaged by the
 * backend). Drawn on canvas each animation frame, so a session's worth of points
 * never touches React state.
 */
export function LiveChart({ windowS = 10 }: { windowS?: number }) {
  const points = useRef<Point[]>([]);
  const [units, setUnits] = useState("kg");
  const cells = useRef<HTMLCanvasElement>(null);
  const total = useRef<HTMLCanvasElement>(null);

  const onMessage = useCallback(
    (m: { units: string; points: Point[] }) => {
      setUnits(m.units);
      if (!m.points.length) return;
      const all = points.current.concat(m.points);
      const newest = all[all.length - 1][1];
      points.current = all.filter((p) => p[1] >= newest - windowS);
    },
    [windowS],
  );
  const status = useSocket("/ws/chart", onMessage);

  useEffect(() => {
    let frame = 0;
    const draw = () => {
      const data = points.current;
      if (cells.current) plot(cells.current, data, [2, 3, 4, 5], CELL_COLOURS, windowS);
      if (total.current) plot(total.current, data, [6], ["#e8edf3"], windowS);
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [windowS]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Live load <span className="muted">· last {windowS} s · {units}{status !== "open" ? ` · ${status}` : ""}</span></h2>
        <div className="legend">
          {CELL_NAMES.map((n, i) => (
            <span key={n}><i style={{ background: CELL_COLOURS[i] }} />{n}</span>
          ))}
        </div>
      </div>
      <canvas ref={cells} className="chart" aria-label="Live load per cell" />
      <p className="chart-title muted">Total load on the deck</p>
      <canvas ref={total} className="chart short" aria-label="Live total load" />
    </section>
  );
}

function plot(canvas: HTMLCanvasElement, data: Point[], columns: number[], colours: string[], windowS: number) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr;
    canvas.height = h * dpr;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (data.length < 2) {
    ctx.fillStyle = "#8b96a5";
    ctx.font = "14px system-ui";
    ctx.fillText("Waiting for data…", 12, 24);
    return;
  }
  const newest = data[data.length - 1][1];
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of data) for (const c of columns) {
    lo = Math.min(lo, p[c]);
    hi = Math.max(hi, p[c]);
  }
  const pad = Math.max((hi - lo) * 0.1, 0.5);
  lo -= pad;
  hi += pad;
  const left = 56;
  const x = (t: number) => left + ((t - (newest - windowS)) / windowS) * (w - left - 8);
  const y = (v: number) => 8 + (1 - (v - lo) / (hi - lo)) * (h - 24);

  ctx.strokeStyle = "#2a313b";
  ctx.fillStyle = "#8b96a5";
  ctx.font = "12px system-ui";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = lo + ((hi - lo) * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y(v));
    ctx.lineTo(w - 8, y(v));
    ctx.stroke();
    ctx.fillText(v.toFixed(Math.abs(hi - lo) < 10 ? 1 : 0), 4, y(v) + 4);
  }
  columns.forEach((c, i) => {
    ctx.strokeStyle = colours[i];
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((p, j) => (j === 0 ? ctx.moveTo(x(p[1]), y(p[c])) : ctx.lineTo(x(p[1]), y(p[c]))));
    ctx.stroke();
  });
}
