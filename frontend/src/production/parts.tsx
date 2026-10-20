import { useEffect, useState } from "react";
import type { Snapshot } from "../types";

/** Shared furniture for the production console. */

export function initials(name: string): string {
  const words = name.replace(/^(dr|mr|mrs|ms)\.?\s+/i, "").trim().split(/\s+/);
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase() || "?";
}

/**
 * The subsystems, for the service screen.
 *
 * Not for therapists. Half of these report nothing the console can observe --
 * the air pump, pressure sensor and e-stop are hardcoded, because that hardware
 * is not wired yet -- and a therapist cannot act on "Pressure Sensor: unknown"
 * anyway. What they need is whether a session can be recorded, which is one
 * question with one answer; see `readiness` below.
 */
export function subsystems(s: Snapshot) {
  const usb = s.link.state === "streaming" ? "ok" : s.link.state === "waiting" ? "warn" : "bad";
  const treadmill = !s.treadmill.available
    ? "off"
    : s.treadmill.connected
      ? (s.treadmill.has_control ? "ok" : "warn")
      : "warn";
  const height = !s.height.available ? "off" : s.height.homed ? "ok" : "warn";
  return [
    { name: "Load Cells", state: usb },
    { name: "Treadmill", state: treadmill },
    { name: "Linear Actuator", state: height },
    { name: "Air Pump", state: "off" },
    { name: "Pressure Sensor", state: "off" },
    { name: "E-Stop", state: "off" },
  ];
}

export function TopBar({ snapshot, right }: { snapshot: Snapshot | null; right?: React.ReactNode }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const problem = readiness(snapshot);

  return (
    <>
      <header className="prod-top">
        <div className="prod-brand">
          <div className="prod-mark">R</div>
          <div>
            <small>REHAX</small>
            <strong>Anti Gravity Treadmill</strong>
          </div>
        </div>
        {/* Silence means ready. A banner that says "all systems operational"
            while the load-cell board is unplugged -- which is what this said,
            because it counted warnings and the board not being there raises
            none -- teaches people to stop reading it. */}
        {problem && (
          <div className={`prod-health ${problem.severity}`} role="status">
            <span className="dot" />
            <span>
              <strong>{problem.what}</strong>
              {problem.todo && <em>{problem.todo}</em>}
            </span>
          </div>
        )}
        {right}
        <div className="prod-clock">
          <div className="time">{now.toLocaleTimeString(undefined, { hour12: false })}</div>
          <div className="date">{now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</div>
        </div>
      </header>

    </>
  );
}

/**
 * The numeric keypad.
 *
 * A modal rather than a docked keyboard because these are single values typed
 * one at a time, and a big centred pad is far easier to hit without looking
 * than a row of small keys at the bottom of a screen.
 */
export function Keypad({ title, initial = "", allowDecimal = false, mask = false, onCancel, onDone }: {
  title: string;
  initial?: string;
  allowDecimal?: boolean;
  mask?: boolean;
  onCancel: () => void;
  onDone: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  const press = (k: string) => {
    if (k === "del") return setValue((v) => v.slice(0, -1));
    if (k === "." && (!allowDecimal || value.includes("."))) return;
    setValue((v) => (v.length >= 12 ? v : v + k));
  };
  return (
    <div className="prod-modal" role="dialog" aria-label={title} onClick={onCancel}>
      <div className="prod-keypad" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <div className="readout" aria-live="polite">
          {mask ? "•".repeat(value.length) : value || <span className="muted">—</span>}
        </div>
        <div className="prod-keys">
          {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((k) => (
            <button key={k} onClick={() => press(k)}>{k}</button>
          ))}
          <button className="del" onClick={() => press("del")} aria-label="Delete">DEL</button>
          <button onClick={() => press("0")}>0</button>
          <button className="ok" onClick={() => onDone(value)} aria-label="OK">OK</button>
          {allowDecimal && <button onClick={() => press(".")} aria-label="Decimal point">.</button>}
        </div>
      </div>
    </div>
  );
}

/** A value that opens the keypad when tapped. Used everywhere a number is entered. */
export function TapNumber({ label, value, unit = "", placeholder = "—", allowDecimal = true, onChange }: {
  label: string;
  value: string;
  unit?: string;
  placeholder?: string;
  allowDecimal?: boolean;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <label className="prod-field">
        <span>{label}</span>
        <button className={`prod-input tap${value ? "" : " empty"}`} onClick={() => setOpen(true)}>
          {value ? `${value}${unit ? ` ${unit}` : ""}` : placeholder}
        </button>
      </label>
      {open && (
        <Keypad
          title={label}
          initial={value}
          allowDecimal={allowDecimal}
          onCancel={() => setOpen(false)}
          onDone={(v) => { onChange(v); setOpen(false); }}
        />
      )}
    </>
  );
}

export function Steps({ current }: { current: number }) {
  const names = ["Patient", "Safety", "Weight", "Balloon", "Offload", "Verify", "Setup", "Session"];
  return (
    <div className="prod-steps">
      {names.map((n, i) => {
        const k = i + 1;
        return (
          <div key={n} className={`prod-step${k < current ? " done" : k === current ? " now" : ""}`}>
            <div className="bubble">{k < current ? "✓" : k}</div>
            <div className="label">{n}</div>
          </div>
        );
      })}
    </div>
  );
}

export interface Readiness {
  severity: "bad" | "warn";
  /** What is wrong, in the therapist's terms. */
  what: string;
  /** What to do about it, when there is something to do. */
  todo?: string;
}

/**
 * Can a session be recorded right now, and if not, why?
 *
 * Returns null when there is nothing to say, and the top bar then shows
 * nothing at all. That is deliberate: in a room where the machine is working
 * almost all of the time, a permanent green badge is read once and then never
 * again, so the one morning it turns red it is not read either.
 *
 * Ordered worst first -- a therapist should be told the thing that stops them,
 * not the first thing the console happens to notice.
 */
export function readiness(s: Snapshot | null): Readiness | null {
  if (s === null) {
    return { severity: "warn", what: "Connecting to the console…" };
  }
  if (s.link.state !== "streaming") {
    return {
      severity: "bad",
      what: "The load cells are not connected",
      todo: "Nothing can be weighed or recorded. Check the USB cable to the board.",
    };
  }
  if (s.calibration.status !== "ok") {
    return {
      severity: "bad",
      what: "No calibration is selected",
      todo: "Every weight comes from it. A technician must set one before a session.",
    };
  }
  const first = s.warnings[0];
  if (first) {
    const more = s.warnings.length - 1;
    return {
      severity: "warn",
      what: first.message,
      todo: more > 0 ? `and ${more} more ${more === 1 ? "warning" : "warnings"}` : undefined,
    };
  }
  return null;
}
