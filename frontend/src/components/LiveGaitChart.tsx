import { useEffect, useRef } from "react";
import type { GaitLive } from "../types";

/**
 * Cadence and step length as they move through a session.
 *
 * The numbers above this tell you where the patient is now; this tells you
 * where they have been, which is the part a therapist actually reads. A cadence
 * that is drifting down over four minutes is fatigue, and it looks identical to
 * a steady one if all you ever see is the current value.
 *
 * Samples come from the live snapshot rather than from the step list, because
 * the snapshot arrives whether or not a step was detected — so a patient who
 * stops walking leaves a visible gap instead of a flat line that pretends
 * nothing changed.
 *
 * Drawn on canvas, with the history in a ref: a session's worth of points must
 * never become React state or every frame re-renders the page.
 */

interface Point {
  t: number;
  cadence: number | null;
  stepLength: number | null;
}

const SERIES = [
  { key: "cadence" as const, label: "cadence", unit: "steps/min", colour: "#4cc2ff" },
  { key: "stepLength" as const, label: "step length", unit: "m", colour: "#3ecf8e" },
];

export function LiveGaitChart({ gait, windowS = 180 }: { gait: GaitLive; windowS?: number }) {
  const points = useRef<Point[]>([]);
  const cadence = useRef<HTMLCanvasElement>(null);
  const stepLength = useRef<HTMLCanvasElement>(null);

  // One sample per snapshot. The snapshot rate is the sample rate, which is
  // plenty for something that changes over tens of seconds.
  useEffect(() => {
    const now = performance.now() / 1000;
    points.current = [
      ...points.current,
      { t: now, cadence: gait.cadence_spm, stepLength: gait.step_length_m },
    ].filter((p) => p.t >= now - windowS);
  }, [gait, windowS]);

  useEffect(() => {
    let frame = 0;
    const draw = () => {
      SERIES.forEach((s, i) => {
        const canvas = i === 0 ? cadence.current : stepLength.current;
        if (canvas) plot(canvas, points.current, s.key, s.colour, windowS, s.unit);
      });
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [windowS]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Gait over time <span className="muted">· last {Math.round(windowS / 60)} min</span></h2>
        <div className="legend">
          {SERIES.map((s) => (
            <span key={s.key}><i style={{ background: s.colour }} />{s.label}</span>
          ))}
        </div>
      </div>
      <canvas ref={cadence} className="chart short" aria-label="Cadence over time" />
      <canvas ref={stepLength} className="chart short" aria-label="Step length over time" />
    </section>
  );
}

function plot(
  canvas: HTMLCanvasElement,
  data: Point[],
  key: "cadence" | "stepLength",
  colour: string,
  windowS: number,
  unit: string,
) {
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

  const known = data.filter((p) => p[key] !== null);
  if (known.length < 2) {
    ctx.fillStyle = "#8b96a5";
    ctx.font = "13px system-ui";
    ctx.fillText("Waiting for steps…", 12, h / 2);
    return;
  }

  const newest = data[data.length - 1].t;
  const values = known.map((p) => p[key] as number);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const pad = Math.max((hi - lo) * 0.2, Math.abs(hi) * 0.05, 0.05);
  lo -= pad;
  hi += pad;

  const left = 52;
  const x = (t: number) => left + ((t - (newest - windowS)) / windowS) * (w - left - 10);
  const y = (v: number) => 10 + (1 - (v - lo) / (hi - lo)) * (h - 26);

  ctx.strokeStyle = "#2a313b";
  ctx.fillStyle = "#8b96a5";
  ctx.font = "11px system-ui";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 2; i++) {
    const v = lo + ((hi - lo) * i) / 2;
    ctx.beginPath();
    ctx.moveTo(left, y(v));
    ctx.lineTo(w - 10, y(v));
    ctx.stroke();
    ctx.fillText(v.toFixed(hi - lo < 3 ? 2 : 0), 4, y(v) + 4);
  }
  ctx.fillText(unit, 4, 10);

  // A gap in the data is drawn as a gap: the patient stopped walking, and
  // joining across it would invent a trend that never happened.
  ctx.strokeStyle = colour;
  ctx.lineWidth = 2;
  ctx.beginPath();
  let drawing = false;
  for (const p of data) {
    const v = p[key];
    if (v === null) {
      drawing = false;
      continue;
    }
    if (!drawing) {
      ctx.moveTo(x(p.t), y(v));
      drawing = true;
    } else {
      ctx.lineTo(x(p.t), y(v));
    }
  }
  ctx.stroke();
}
