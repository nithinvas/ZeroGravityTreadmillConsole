import { useEffect, useRef } from "react";

/**
 * A chart you can zoom into with your fingers.
 *
 * Built for the touch screen on the machine, not a mouse: drag to pan, pinch to
 * zoom, double-tap to go back to the whole session. Buttons do the same thing,
 * because pinching accurately on a wall-mounted panel with gloves on is harder
 * than it looks.
 *
 * Several charts share one `range`, so zooming into a step on one load cell
 * zooms every other cell to the same moment. That is the whole point: a
 * therapist comparing corners needs them on the same axis, not four charts that
 * happen to look similar.
 *
 * Canvas rather than SVG: a four-minute session is a few thousand points per
 * cell, and five of these on screen at once is enough to make SVG crawl on the
 * mini PC's integrated graphics.
 */

export interface Range { lo: number; hi: number }
export interface Series {
  name: string;
  colour: string;
  /** [x, y] pairs. A null y breaks the line, leaving a visible gap. */
  points: [number, number | null][];
}

export function ZoomChart({
  series, range, onRange, yLabel, height = 150, bounds, zeroLine = false,
}: {
  series: Series[];
  range: Range;
  onRange: (r: Range) => void;
  yLabel?: string;
  height?: number;
  /** Full extent of the data, used to clamp panning and to reset. */
  bounds: Range;
  zeroLine?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ x: number; lo: number; hi: number } | null>(null);
  const pinch = useRef<{ d: number; lo: number; hi: number } | null>(null);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = el.clientWidth || 600;
    if (el.width !== w * dpr || el.height !== height * dpr) {
      el.width = w * dpr; el.height = height * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, height);

    const pad = { l: 52, r: 10, t: 10, b: 20 };
    const pw = Math.max(1, w - pad.l - pad.r);
    const ph = Math.max(1, height - pad.t - pad.b);

    // Scale y to what is visible, so zooming in also zooms the detail.
    let lo = Infinity, hi = -Infinity;
    for (const s of series) {
      for (const [x, y] of s.points) {
        if (y === null || x < range.lo || x > range.hi) continue;
        if (y < lo) lo = y;
        if (y > hi) hi = y;
      }
    }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (zeroLine) lo = Math.min(lo, 0);
    const span = hi - lo || 1;
    lo -= span * 0.08; hi += span * 0.08;

    const X = (v: number) => pad.l + ((v - range.lo) / (range.hi - range.lo)) * pw;
    const Y = (v: number) => pad.t + ph - ((v - lo) / (hi - lo)) * ph;

    ctx.strokeStyle = "rgba(148,163,184,.18)";
    ctx.fillStyle = "rgba(148,163,184,.75)";
    ctx.font = "10px system-ui, sans-serif";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const v = lo + ((hi - lo) * i) / 3;
      const yy = Y(v);
      ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(w - pad.r, yy); ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(v.toFixed(Math.abs(hi - lo) < 5 ? 1 : 0), pad.l - 6, yy + 3);
    }
    ctx.textAlign = "center";
    for (let i = 0; i <= 4; i++) {
      const v = range.lo + ((range.hi - range.lo) * i) / 4;
      ctx.fillText(`${v.toFixed(range.hi - range.lo < 8 ? 1 : 0)}s`, X(v), height - 5);
    }
    if (yLabel) {
      ctx.save(); ctx.translate(11, pad.t + ph / 2); ctx.rotate(-Math.PI / 2);
      ctx.textAlign = "center"; ctx.fillText(yLabel, 0, 0); ctx.restore();
    }

    for (const s of series) {
      const vis = s.points.filter(([x]) => x >= range.lo - 1 && x <= range.hi + 1);
      if (!vis.length) continue;

      if (vis.length > pw * 1.5) {
        // More samples than pixels. Drawing a polyline here is not a smaller
        // version of the signal, it is aliasing -- a 2.7 Hz walking rhythm into
        // a 1.6-pixel step reads as a solid band of noise, which is what this
        // chart used to show.
        //
        // So draw what each pixel column actually contains: a vertical line
        // from its lowest sample to its highest. The envelope is honest at any
        // zoom, and keeps the peaks. A moving average would smooth them away,
        // and the peak is the clinically interesting part.
        const lows = new Float64Array(pw).fill(Infinity);
        const highs = new Float64Array(pw).fill(-Infinity);
        for (const [x, y] of vis) {
          if (y === null) continue;
          const c = Math.min(pw - 1, Math.max(0, Math.floor(((x - range.lo) / (range.hi - range.lo)) * pw)));
          if (y < lows[c]) lows[c] = y;
          if (y > highs[c]) highs[c] = y;
        }
        ctx.fillStyle = s.colour;
        ctx.globalAlpha = 0.85;
        for (let c = 0; c < pw; c++) {
          if (lows[c] === Infinity) continue;         // a gap stays a gap
          const top = Y(highs[c]);
          ctx.fillRect(pad.l + c, top, 1, Math.max(1, Y(lows[c]) - top));
        }
        ctx.globalAlpha = 1;
        continue;
      }

      ctx.strokeStyle = s.colour;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      let open = false;
      for (const [x, y] of vis) {
        if (y === null) { open = false; continue; }   // a gap stays a gap
        if (open) ctx.lineTo(X(x), Y(y)); else { ctx.moveTo(X(x), Y(y)); open = true; }
      }
      ctx.stroke();
    }

  }, [series, range, height, yLabel, zeroLine]);

  const clamp = (lo: number, hi: number): Range => {
    const minSpan = 0.4;
    if (hi - lo < minSpan) { const m = (lo + hi) / 2; lo = m - minSpan / 2; hi = m + minSpan / 2; }
    const full = bounds.hi - bounds.lo;
    if (hi - lo > full) return { ...bounds };
    if (lo < bounds.lo) { hi += bounds.lo - lo; lo = bounds.lo; }
    if (hi > bounds.hi) { lo -= hi - bounds.hi; hi = bounds.hi; }
    return { lo, hi };
  };

  const span = range.hi - range.lo;
  const zoom = (factor: number) => {
    const m = (range.lo + range.hi) / 2;
    onRange(clamp(m - (span * factor) / 2, m + (span * factor) / 2));
  };

  const touches = (e: React.TouchEvent) => {
    const w = canvas.current?.clientWidth || 1;
    if (e.touches.length === 2) {
      const d = Math.abs(e.touches[0].clientX - e.touches[1].clientX);
      if (!pinch.current) pinch.current = { d, lo: range.lo, hi: range.hi };
      else if (d > 10) {
        const k = pinch.current.d / d;
        const m = (pinch.current.lo + pinch.current.hi) / 2;
        const s = (pinch.current.hi - pinch.current.lo) * k;
        onRange(clamp(m - s / 2, m + s / 2));
      }
      drag.current = null;
      return;
    }
    pinch.current = null;
    const x = e.touches[0].clientX;
    if (!drag.current) drag.current = { x, lo: range.lo, hi: range.hi };
    else {
      const dx = ((drag.current.x - x) / w) * (drag.current.hi - drag.current.lo);
      onRange(clamp(drag.current.lo + dx, drag.current.hi + dx));
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <canvas
        ref={canvas}
        style={{ width: "100%", height, display: "block", touchAction: "none", cursor: "grab" }}
        onTouchStart={touches}
        onTouchMove={touches}
        onTouchEnd={() => { drag.current = null; pinch.current = null; }}
        onDoubleClick={() => onRange({ ...bounds })}
        onWheel={(e) => { zoom(e.deltaY > 0 ? 1.25 : 0.8); }}
        onMouseDown={(e) => { drag.current = { x: e.clientX, lo: range.lo, hi: range.hi }; }}
        onMouseMove={(e) => {
          if (!drag.current) return;
          const w = canvas.current?.clientWidth || 1;
          const dx = ((drag.current.x - e.clientX) / w) * (drag.current.hi - drag.current.lo);
          onRange(clamp(drag.current.lo + dx, drag.current.hi + dx));
        }}
        onMouseUp={() => { drag.current = null; }}
        onMouseLeave={() => { drag.current = null; }}
      />
    </div>
  );
}

/** Shared zoom controls, placed once above a stack of linked charts. */
export function ZoomBar({ range, bounds, onRange }: {
  range: Range; bounds: Range; onRange: (r: Range) => void;
}) {
  const span = range.hi - range.lo;
  const full = bounds.hi - bounds.lo;
  const shift = (by: number) => {
    let lo = range.lo + by * span, hi = range.hi + by * span;
    if (lo < bounds.lo) { hi += bounds.lo - lo; lo = bounds.lo; }
    if (hi > bounds.hi) { lo -= hi - bounds.hi; hi = bounds.hi; }
    onRange({ lo, hi });
  };
  const zoom = (f: number) => {
    const m = (range.lo + range.hi) / 2;
    let s = Math.min(Math.max(span * f, 0.4), full);
    let lo = m - s / 2, hi = m + s / 2;
    if (lo < bounds.lo) { hi += bounds.lo - lo; lo = bounds.lo; }
    if (hi > bounds.hi) { lo -= hi - bounds.hi; hi = bounds.hi; }
    onRange({ lo, hi });
  };
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
      <button className="prod-btn ghost" onClick={() => shift(-0.5)} disabled={range.lo <= bounds.lo}>←</button>
      <button className="prod-btn ghost" onClick={() => zoom(0.5)}>Zoom in</button>
      <button className="prod-btn ghost" onClick={() => zoom(2)} disabled={span >= full}>Zoom out</button>
      <button className="prod-btn ghost" onClick={() => shift(0.5)} disabled={range.hi >= bounds.hi}>→</button>
      <button className="prod-btn ghost" onClick={() => onRange({ ...bounds })} disabled={span >= full}>
        Whole session
      </button>
      <span className="muted" style={{ fontSize: 12, marginLeft: "auto" }}>
        {range.lo.toFixed(1)}–{range.hi.toFixed(1)} s of {full.toFixed(0)} s
        {span > 25
          ? " · showing the range each step covers — zoom in for the trace"
          : " · showing the trace"}
      </span>
    </div>
  );
}
