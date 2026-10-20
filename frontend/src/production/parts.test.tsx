import { describe, expect, it } from "vitest";
import type { Snapshot } from "../types";
import { readiness } from "./parts";

/**
 * The top bar used to say "All Systems Operational" whenever the console had
 * raised no warnings — which it does not when the load-cell board is simply
 * absent. So it read "All Systems Operational" with the board unplugged. These
 * tests exist to keep that from coming back.
 */

const ok = {
  link: { state: "streaming", device: {} },
  calibration: { status: "ok" },
  warnings: [],
  app: { version: "0.1.0" },
} as unknown as Snapshot;

const withLink = (state: string) =>
  ({ ...ok, link: { ...ok.link, state } }) as unknown as Snapshot;

describe("readiness", () => {
  it("says nothing at all when the machine is ready", () => {
    expect(readiness(ok)).toBeNull();
  });

  it("does not claim everything is fine when the board is unplugged", () => {
    const r = readiness(withLink("waiting"));
    expect(r?.severity).toBe("bad");
    expect(r?.what).toMatch(/load cells are not connected/i);
    expect(r?.todo).toMatch(/usb/i);
  });

  it("stops a session when no calibration is selected", () => {
    const r = readiness({ ...ok, calibration: { status: "missing" } } as unknown as Snapshot);
    expect(r?.severity).toBe("bad");
    expect(r?.what).toMatch(/no calibration/i);
  });

  it("reports the missing board ahead of lesser warnings", () => {
    const s = { ...withLink("waiting"), warnings: [{ code: "x", message: "Something minor" }] } as unknown as Snapshot;
    expect(readiness(s)?.what).toMatch(/load cells/i);
  });

  it("surfaces a warning's own words rather than a count", () => {
    const s = { ...ok, warnings: [{ code: "drift", message: "The deck has drifted 2 kg" }] } as unknown as Snapshot;
    const r = readiness(s);
    expect(r?.severity).toBe("warn");
    expect(r?.what).toBe("The deck has drifted 2 kg");
    expect(r?.todo).toBeUndefined();
  });

  it("counts the rest when there is more than one warning", () => {
    const s = { ...ok, warnings: [
      { code: "a", message: "First thing" },
      { code: "b", message: "Second thing" },
      { code: "c", message: "Third thing" },
    ] } as unknown as Snapshot;
    expect(readiness(s)?.todo).toBe("and 2 more warnings");
  });

  it("says so while the console is still connecting", () => {
    expect(readiness(null)?.what).toMatch(/connecting/i);
  });
});
