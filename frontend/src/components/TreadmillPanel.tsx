import { useState } from "react";
import { postJson } from "../api";
import { fmtNum } from "../format";
import type { TreadmillState } from "../types";

interface Props {
  treadmill: TreadmillState;
  /** Compact form for the side column; the session dashboard uses the full one. */
  compact?: boolean;
}

/**
 * Treadmill control over Bluetooth.
 *
 * Start and stop are disabled by what the machine reports rather than by what was
 * last pressed, so a belt stopped at its own console (or by the safety key) leaves
 * the console's Start button live and Stop greyed, matching the room.
 */
export function TreadmillPanel({ treadmill: t, compact = false }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const send = async (what: string, path: string, body?: object) => {
    setBusy(what);
    setError(null);
    try {
      await postJson(path, body ?? {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const speedStep = t.limits.speed_step_kph || 0.1;
  const inclineStep = t.limits.incline_step_percent || 1;
  const working = busy !== null;

  if (!t.available) {
    return (
      <section className="panel treadmill">
        <h2>Treadmill</h2>
        <p className="muted">
          This console was started without treadmill control, so speed and incline are entered by
          hand and set on the treadmill itself.
        </p>
      </section>
    );
  }

  return (
    <section className="panel treadmill">
      <div className="panel-head">
        <h2>Treadmill <span className="muted">· Bluetooth</span></h2>
        <div className={`pill pill-${t.connected ? (t.has_control ? "streaming" : "waiting") : "disconnected"}`}>
          <span className="dot" />
          {t.connected ? (t.has_control ? "Connected" : "No control") : t.state === "connecting" ? "Searching" : "Not connected"}
        </div>
      </div>

      {!t.connected && (
        <>
          <p className={t.state === "failed" ? "error" : "muted"}>{t.detail}</p>
          <p className="hint">
            The session still records over USB without it — connecting only adds belt control.
          </p>
        </>
      )}
      {t.connected && !t.has_control && (
        <p className="error">
          Connected to {t.device_name}, but the machine has not granted control. Check nothing else
          is paired with it, then reconnect.
        </p>
      )}
      {t.safety_key_pulled && (
        <div className="warning severe">
          <span className="warning-icon" aria-hidden="true">!</span>
          <span>The safety key was pulled. Refit it at the treadmill before starting again.</span>
        </div>
      )}

      {t.connected && (
        <div className="treadmill-readout">
          <Readout label="Speed" target={t.target_speed_kph} reported={t.reported_speed_kph}
            unit="km/h" digits={1} />
          <Readout label="Incline" target={t.target_incline_percent} reported={t.reported_incline_percent} unit="%" digits={0} />
          <div className="metric small">
            <div className="metric-label">Belt</div>
            <div className={`metric-value ${t.running ? "on" : "off"}`}>{t.running ? "Running" : "Stopped"}</div>
          </div>
        </div>
      )}

      <div className="actions">
        {!t.connected ? (
          <button className="btn primary" disabled={working || t.state === "connecting"}
            onClick={() => send("connect", "/api/treadmill/connect")}>
            {busy === "connect" || t.state === "connecting" ? "Searching…" : t.state === "failed" ? "Try again" : "Check connection"}
          </button>
        ) : (
          <>
            <button className="btn primary" disabled={!t.can_start || working}
              onClick={() => send("start", "/api/treadmill/start")}>Start belt</button>
            <button className="btn danger" disabled={!t.can_stop || working}
              onClick={() => send("stop", "/api/treadmill/stop")}>Stop belt</button>
            {!compact && (
              <button className="btn ghost" disabled={working}
                onClick={() => send("disconnect", "/api/treadmill/disconnect")}>Disconnect</button>
            )}
          </>
        )}
      </div>

      {t.connected && (
        <div className="treadmill-controls">
          <div className="control-row">
            <span className="control-label">Speed</span>
            <button className="btn big" disabled={!t.can_change_speed || working}
              onClick={() => send("s-", "/api/treadmill/speed", { steps: -1 })}
              aria-label="Slower">−{fmtNum(speedStep, 1)}</button>
            <span className="control-value">
              {t.target_speed_kph === null ? "—" : fmtNum(t.target_speed_kph, 1)}
              <small> km/h</small>
            </span>
            <button className="btn big" disabled={!t.can_change_speed || working}
              onClick={() => send("s+", "/api/treadmill/speed", { steps: 1 })}
              aria-label="Faster">+{fmtNum(speedStep, 1)}</button>
          </div>
          <div className="control-row">
            <span className="control-label">Incline</span>
            <button className="btn big" disabled={!t.has_control || working}
              onClick={() => send("i-", "/api/treadmill/incline", { steps: -1 })}
              aria-label="Less incline">−{fmtNum(inclineStep, 0)}</button>
            <span className="control-value">{t.target_incline_percent === null ? "—" : fmtNum(t.target_incline_percent, 0)}<small> %</small></span>
            <button className="btn big" disabled={!t.has_control || working}
              onClick={() => send("i+", "/api/treadmill/incline", { steps: 1 })}
              aria-label="More incline">+{fmtNum(inclineStep, 0)}</button>
          </div>
          <p className="hint">
            {t.running
              ? `${fmtNum(t.limits.min_speed_kph, 1)}–${fmtNum(t.limits.max_speed_kph, 1)} km/h. ` +
                "Each change starts a new block in the report, and the speed you set here is the " +
                "one step and stride length are measured against."
              : `The belt is stopped. Start brings it up at ${fmtNum(t.session_start_speed_kph, 1)} ` +
                "km/h, every time, so nobody steps onto a moving deck."}
          </p>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}

/** Target and reported side by side: the belt lags the target while the motor ramps. */
function Readout({ label, target, reported, unit, digits }: {
  label: string; target: number | null; reported: number | null; unit: string; digits: number;
}) {
  return (
    <div className="metric small">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{target === null ? "—" : fmtNum(target, digits)}<small> {unit}</small></div>
      <div className="metric-unit">belt {reported === null ? "—" : fmtNum(reported, digits)}</div>
    </div>
  );
}
