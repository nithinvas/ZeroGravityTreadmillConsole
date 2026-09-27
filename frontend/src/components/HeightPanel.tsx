import { useEffect, useState } from "react";
import { postJson } from "../api";
import { fmtNum } from "../format";
import type { HeightState } from "../types";

/**
 * Belt height, set before the patient steps on.
 *
 * Two things shape this panel. The mechanism reports nothing back, so every
 * number here is what the console asked for — the panel says so rather than
 * implying a measurement. And a full-travel move takes the best part of a
 * minute, so a move in progress gets a real progress bar and a working Stop,
 * not a spinner.
 */
export function HeightPanel({ height: h }: { height: HeightState }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Follow the deck while it is not being typed into, so the box always shows
  // where the console believes the deck is.
  useEffect(() => {
    if (document.activeElement?.id !== "height-entry") {
      setTyped(h.target_mm === null ? "" : String(h.target_mm));
    }
  }, [h.target_mm]);

  const send = async (path: string, body?: object) => {
    setBusy(true);
    setError(null);
    try {
      await postJson(path, body ?? {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const applyTyped = () => {
    const mm = Number(typed);
    if (!Number.isFinite(mm)) {
      setError("Enter a height in millimetres.");
      return;
    }
    void send("/api/height/move", { mm });
  };

  if (!h.available) {
    return (
      <section className="panel">
        <h2>Belt height</h2>
        <p className="muted">
          This console was started without belt-height control, so the deck is set at the
          treadmill itself.
        </p>
      </section>
    );
  }

  const locked = h.locked_by_session;
  const disabled = !h.can_move || busy;

  return (
    <section className="panel height">
      <div className="panel-head">
        <h2>Belt height</h2>
        <div className={`pill pill-${h.moving ? "waiting" : h.homed ? "streaming" : "disconnected"}`}>
          <span className="dot" />
          {h.moving ? "Moving" : h.homed ? "Ready" : "Not homed"}
        </div>
      </div>

      {locked && (
        <p className="muted">
          A session is recording. The deck stays where it is until the session ends.
        </p>
      )}

      {!h.homed && !locked && (
        <>
          <p className="muted">
            The deck's position is not known yet — it has to find its end stops before it can be
            set to a height. Nobody should be on the deck while it homes.
          </p>
          <button className="btn primary big" disabled={busy || h.moving}
            onClick={() => send("/api/height/home")}>
            {h.moving ? "Homing…" : "Home the deck"}
          </button>
        </>
      )}

      {h.homed && (
        <>
          <div className="height-readout">
            <div className="metric">
              <div className="metric-label">Set to</div>
              <div className="metric-value">{h.target_mm === null ? "—" : h.target_mm}<small> mm</small></div>
              <div className="metric-unit">{h.min_mm}–{h.max_mm} mm</div>
            </div>
          </div>

          <div className="control-row">
            <button className="btn big" disabled={disabled}
              onClick={() => send("/api/height/move", { steps: -1 })}
              aria-label="Lower">−{h.step_mm}</button>
            <label className="height-entry" htmlFor="height-entry">
              <input id="height-entry" inputMode="numeric" value={typed} disabled={disabled}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && applyTyped()} />
              <span>mm</span>
            </label>
            <button className="btn big" disabled={disabled}
              onClick={() => send("/api/height/move", { steps: 1 })}
              aria-label="Raise">+{h.step_mm}</button>
          </div>

          <div className="actions">
            <button className="btn primary" disabled={disabled || typed === String(h.target_mm ?? "")}
              onClick={applyTyped}>Go to this height</button>
            <button className="btn ghost" disabled={busy || h.moving || locked}
              onClick={() => send("/api/height/home")}>Re-home</button>
          </div>

          <p className="hint">
            Steps of {h.step_mm} mm, or type a height and press Enter. This is what the console
            asked for — the mechanism does not report its own position back.
          </p>
        </>
      )}

      {h.moving && (
        <div className="height-progress" role="status">
          {/* Homing has no countdown to give: it ends when the switch is found,
              which is usually long before the worst case. Showing the timeout as
              progress would just look broken. */}
          <div className={`bar${h.homing ? " indeterminate" : ""}`}>
            <span style={h.homing ? undefined : { width: `${h.progress * 100}%` }} />
          </div>
          <div className="progress-row">
            <span>
              {h.homing
                ? "Homing — the deck stops as soon as it reaches its end stops. Keep clear."
                : `Moving the deck — about ${fmtNum(h.seconds_left, 0)} s left. Keep clear.`}
            </span>
            <button className="btn danger" onClick={() => send("/api/height/stop")}>Stop</button>
          </div>
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {!error && h.last_error && <p className="error">{h.last_error}</p>}
    </section>
  );
}
