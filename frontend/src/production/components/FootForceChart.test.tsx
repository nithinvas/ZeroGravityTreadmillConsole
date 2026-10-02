import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FootForceChart, type FootPoint } from "./FootForceChart";

/**
 * The chart's one job that cannot be got wrong: a gap must stay a gap.
 *
 * Where the console could not resolve which foot was carrying the load, the
 * value is null. Drawing a line through those points would produce a smooth
 * curve that looks like a measurement -- and on this chart a wrong curve looks
 * exactly like a patient favouring one leg.
 */

const calls: { op: string; args: unknown[] }[] = [];

function stubCanvas() {
  const ctx = new Proxy({}, {
    get(_t, prop: string) {
      if (prop === "setTransform" || prop === "clearRect") return () => undefined;
      if (prop === "canvas") return undefined;
      return (...args: unknown[]) => { calls.push({ op: prop, args }); };
    },
    set() { return true; },
  });
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx) as never;
  Object.defineProperty(HTMLCanvasElement.prototype, "clientWidth", { value: 600, configurable: true });
}

beforeEach(() => {
  calls.length = 0;
  stubCanvas();
});

/** Two strides of left foot, with the middle of the second one unresolved. */
function trace(): FootPoint[] {
  const pts: FootPoint[] = [];
  for (let i = 0; i < 60; i++) {
    const gap = i >= 30 && i < 36;
    pts.push({
      t: i * 0.04,
      left: gap ? null : Math.max(0, Math.sin((i / 60) * Math.PI * 4)) * 70,
      right: gap ? null : Math.max(0, -Math.sin((i / 60) * Math.PI * 4)) * 70,
    });
  }
  return pts;
}

describe("FootForceChart", () => {
  it("breaks the line across an unresolved stretch instead of drawing through it", () => {
    render(<FootForceChart points={trace()} bodyWeightKg={70} showAll />);
    const strokes = calls.filter((c) => c.op === "beginPath").length;
    // One path per foot, and each must restart after the gap rather than
    // joining across it: at least two moveTo per foot.
    const moves = calls.filter((c) => c.op === "moveTo").length;
    expect(strokes).toBeGreaterThanOrEqual(2);
    expect(moves).toBeGreaterThanOrEqual(4);
  });

  /** The two reference lines -- body weight and zero -- are always drawn. */
  const REFERENCE_LINES = 2;

  it("draws only the reference lines when nothing could be resolved", () => {
    const pts = trace().map((p) => ({ ...p, left: null, right: null }));
    expect(() => render(<FootForceChart points={pts} bodyWeightKg={70} />)).not.toThrow();
    expect(calls.filter((c) => c.op === "lineTo")).toHaveLength(REFERENCE_LINES);
  });

  it("draws nothing at all for an empty trace", () => {
    render(<FootForceChart points={[]} bodyWeightKg={70} />);
    expect(calls.filter((c) => c.op === "lineTo")).toHaveLength(0);
  });

  it("does draw the curves when the trace is resolved", () => {
    render(<FootForceChart points={trace()} bodyWeightKg={70} showAll />);
    expect(calls.filter((c) => c.op === "lineTo").length).toBeGreaterThan(REFERENCE_LINES + 20);
  });

  it("names both feet so the colours are not the only cue", () => {
    const { getByText } = render(<FootForceChart points={trace()} bodyWeightKg={70} />);
    expect(getByText("Left foot")).toBeInTheDocument();
    expect(getByText("Right foot")).toBeInTheDocument();
  });
});
