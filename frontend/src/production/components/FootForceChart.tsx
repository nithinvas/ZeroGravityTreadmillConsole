import { useEffect, useRef } from "react";

/**
 * The two per-foot force curves, drawn the way a dual force plate would show
 * them: one trace per foot, each rising from nothing, peaking twice, and
 * returning to nothing while that foot is in the air.
 *
 * The zeros are the point. A single deck measures both feet at once and its
 * total never reaches zero, which hides exactly the thing a therapist is
 * looking for -- whether a patient is really unloading a limb, and by how much.
 *
 * Where the console could not resolve the hand-over the value arrives as null
 * and the line breaks. A gap reads as missing data, which is honest; a line
 * drawn through it would read as a measurement, and here it would be a lie
 * shaped exactly like a limp.
 */

export interface FootPoint {
  t: number;
  left: number | null;
  right: number | null;
}

const LEFT = "#38bdf8";
const RIGHT = "#fb7185";

export function FootForceChart({
  points, bodyWeightKg, seconds, height = 150, showAll = false,
}: {
  points: FootPoint[];
  bodyWeightKg: number;
  /** Seconds of history to show. Ignored when showAll is set. */
  seconds?: number;
  height?: number;
  /** The report draws the whole session; the live screen a rolling window. */
  showAll?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = el.clientWidth || 600;
    const h = height;
    if (el.width !== w * dpr || el.height !== h * dpr) {
      el.width = w * dpr;
      el.height = h * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (points.length < 2) return;

    const pad = { l: 36, r: 10, t: 10, b: 18 };
    const plotW = Math.max(1, w - pad.l - pad.r);
    const plotH = Math.max(1, h - pad.t - pad.b);

    const last = points[points.length - 1].t;
    const span = showAll ? Math.max(1, last - points[0].t) : (seconds ?? 10);
    const start = showAll ? points[0].t : last - span;

    let peak = bodyWeightKg * 1.3;
    for (const p of points) {
      if (p.left !== null && p.left > peak) peak = p.left;
      if (p.right !== null && p.right > peak) peak = p.right;
    }
    const top = peak * 1.12 || 1;

    const x = (t: number) => pad.l + ((t - start) / span) * plotW;
    const y = (v: number) => pad.t + plotH - (v / top) * plotH;

    ctx.strokeStyle = "rgba(148,163,184,.30)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.l, y(bodyWeightKg));
    ctx.lineTo(w - pad.r, y(bodyWeightKg));
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = "rgba(148,163,184,.22)";
    ctx.beginPath();
    ctx.moveTo(pad.l, y(0));
    ctx.lineTo(w - pad.r, y(0));
    ctx.stroke();

    ctx.fillStyle = "rgba(148,163,184,.8)";
    ctx.font = "10px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(String(Math.round(bodyWeightKg)), pad.l - 5, y(bodyWeightKg) + 3);
    ctx.fillText("0", pad.l - 5, y(0) + 3);

    for (const [key, colour] of [["left", LEFT], ["right", RIGHT]] as const) {
      ctx.lineWidth = 1.9;
      ctx.strokeStyle = colour;
      ctx.beginPath();
      let open = false;
      for (const p of points) {
        if (p.t < start) continue;
        const v = p[key];
        if (v === null) { open = false; continue; }
        if (open) ctx.lineTo(x(p.t), y(v));
        else { ctx.moveTo(x(p.t), y(v)); open = true; }
      }
      ctx.stroke();
    }
  }, [points, bodyWeightKg, seconds, height, showAll]);

  return (
    <div>
      <canvas ref={canvas} style={{ width: "100%", height, display: "block" }} />
      <div style={{ display: "flex", gap: 16, fontSize: 11.5, color: "var(--muted, #7e8fa0)", marginTop: 4 }}>
        <Key colour={LEFT} label="Left foot" />
        <Key colour={RIGHT} label="Right foot" />
        <span style={{ marginLeft: "auto" }}>dotted line = body weight</span>
      </div>
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
