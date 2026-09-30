import { useEffect, useState } from "react";
import type { Snapshot } from "../types";

/** Shared furniture for the production console. */

export function initials(name: string): string {
  const words = name.replace(/^(dr|mr|mrs|ms)\.?\s+/i, "").trim().split(/\s+/);
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase() || "?";
}

/**
 * The subsystems a therapist needs to know the state of before putting someone
 * on the machine. Anything the console cannot actually observe yet is shown as
 * unknown rather than green — a dot that is always green tells you nothing, and
 * would be a lie on the two that are still prototype hardware.
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

  const warnings = snapshot?.warnings.length ?? 0;
  const healthy = snapshot !== null && warnings === 0;

  return (
    <>
      <header className="prod-top">
        <div className="prod-brand">
          <div className="prod-mark">Z</div>
          <div>
            <small>ZERO GRAVITY</small>
            <strong>Rehabilitation Treadmill</strong>
          </div>
        </div>
        <div className={`prod-health${healthy ? "" : " bad"}`}>
          <span className="dot" />
          {snapshot === null
            ? "Connecting…"
            : warnings === 0
              ? "All Systems Operational"
              : `${warnings} ${warnings === 1 ? "warning" : "warnings"}`}
        </div>
        {right}
        <div className="prod-clock">
          <div className="time">{now.toLocaleTimeString(undefined, { hour12: false })}</div>
          <div className="date">{now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</div>
        </div>
      </header>
      {snapshot && (
        <div className="prod-subsystems">
          {subsystems(snapshot).map((x) => (
            <span key={x.name}><i className={x.state} />{x.name}</span>
          ))}
          <span className="fw">
            v{snapshot.app.version}
            {snapshot.link.device.bcd_device ? ` · fw ${snapshot.link.device.bcd_device}` : ""}
          </span>
        </div>
      )}
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
