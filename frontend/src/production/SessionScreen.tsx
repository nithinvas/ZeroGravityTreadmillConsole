import { useState } from "react";
import { postJson } from "../api";
import { fmtDuration, fmtNum } from "../format";
import { LiveChart } from "../components/LiveChart";
import { LiveGaitChart } from "../components/LiveGaitChart";
import type { SessionLive, Snapshot } from "../types";

/**
 * The screen a therapist watches while somebody is walking.
 *
 * Laid out so the numbers that change are readable from beside the treadmill
 * rather than in front of the screen, and so the two controls that matter in a
 * hurry — stop the belt, end the session — are never more than one press away
 * and never move.
 */
export function SessionScreen({ snapshot, session, bwsPercent, onFinished }: {
  snapshot: Snapshot;
  session: SessionLive;
  bwsPercent: number;
  onFinished: (id: string) => void;
}) {
  const [tab, setTab] = useState<"live" | "gait">("live");
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const g = session.gait;
  const t = snapshot.treadmill;
  const controlled = t.connected && t.has_control;

  const send = (path: string, body?: object) =>
    postJson(path, body ?? {}).catch((e) => setError((e as Error).message));

  const stopEverything = async () => {
    // Belt first, always: ending the session writes files, and nobody should be
    // waiting on a disk while the deck is still moving under them.
    await send("/api/treadmill/stop");
  };

  const endSession = async () => {
    setStopping(true);
    try {
      const result = await postJson<{ meta: { id: string } }>("/api/sessions/current/stop", {});
      onFinished(result.meta.id);
    } catch (e) {
      setError((e as Error).message);
      setStopping(false);
    }
  };

  return (
    <>
      <div className="prod-session-top">
        <div>
          <strong>{session.details.patient_name || session.details.patient_id}</strong>
          <div className="muted mono" style={{ fontSize: 12 }}>{session.details.patient_id}</div>
        </div>
        <div className="mono" style={{ fontSize: 20, fontWeight: 700 }}>
          {fmtDuration(session.elapsed_s)}
        </div>
        <div className="muted" style={{ fontSize: 12 }}>
          {bwsPercent}% BWS · {session.condition.speed_kph === null ? "belt stopped" : `${session.condition.speed_kph} km/h`}
        </div>
        <button className="prod-estop" style={{ marginLeft: "auto" }} onClick={stopEverything}>
          ■ STOP BELT
        </button>
      </div>

      <div className="prod-metrics">
        <Metric label="Cadence" value={fmtNum(g.cadence_spm, 0)} unit="steps/min" tone="info" />
        <Metric label="Step length" value={fmtNum(g.step_length_m, 2)} unit="m" />
        <Metric label="Stride length" value={fmtNum(g.stride_length_m, 2)} unit="m" />
        <Metric label="Distance" value={fmtNum(session.distance_m, 1)} unit="m" />
        <Metric label="Walking" value={fmtDuration(session.walking_s)} unit="of session" />
        <Metric label="Offloading" value={String(bwsPercent)} unit="% (not applied)" tone="warn" />
      </div>

      {controlled && (
        <div style={{ display: "flex", gap: 40, justifyContent: "center", padding: "16px 0", borderBottom: "1px solid var(--line)" }}>
          <div>
            <div className="prod-eyebrow" style={{ textAlign: "center", marginBottom: 8 }}>Speed</div>
            <div className="prod-stepper">
              <button disabled={!t.can_change_speed} aria-label="Slower"
                onClick={() => send("/api/treadmill/speed", { steps: -1 })}>−</button>
              <span className="val">{t.target_speed_kph === null ? "—" : fmtNum(t.target_speed_kph, 1)}</span>
              <button disabled={!t.can_change_speed} aria-label="Faster"
                onClick={() => send("/api/treadmill/speed", { steps: 1 })}>+</button>
            </div>
          </div>
          <div>
            <div className="prod-eyebrow" style={{ textAlign: "center", marginBottom: 8 }}>Incline</div>
            <div className="prod-stepper">
              <button disabled={!t.has_control} aria-label="Less incline"
                onClick={() => send("/api/treadmill/incline", { steps: -1 })}>−</button>
              <span className="val">{t.target_incline_percent === null ? "—" : fmtNum(t.target_incline_percent, 0)}%</span>
              <button disabled={!t.has_control} aria-label="More incline"
                onClick={() => send("/api/treadmill/incline", { steps: 1 })}>+</button>
            </div>
          </div>
          <div>
            <div className="prod-eyebrow" style={{ textAlign: "center", marginBottom: 8 }}>Belt</div>
            <div className="prod-stepper">
              <button className="prod-btn" disabled={!t.can_start}
                onClick={() => send("/api/treadmill/start")}>Start</button>
              <button className="prod-btn danger" disabled={!t.can_stop}
                onClick={() => send("/api/treadmill/stop")}>Stop</button>
            </div>
          </div>
        </div>
      )}

      <div className="prod-tabs">
        <button className={`prod-tab${tab === "live" ? " on" : ""}`} onClick={() => setTab("live")}>
          Live metrics
        </button>
        <button className={`prod-tab${tab === "gait" ? " on" : ""}`} onClick={() => setTab("gait")}>
          Gait analysis
        </button>
        <span className="muted" style={{ marginLeft: "auto", alignSelf: "center", fontSize: 12.5 }}>
          {g.prompt ?? `${g.steps_accepted} of ${g.steps_total} steps accepted`}
        </span>
      </div>

      <div style={{ padding: 18 }}>
        {error && <div className="prod-error" role="alert">{error}</div>}
        {tab === "live" ? <LiveChart /> : <LiveGaitChart gait={g} />}

        <div style={{ display: "flex", gap: 14, marginTop: 18 }}>
          <div className="grow" style={{ flex: 1 }} />
          <button className="prod-btn danger big" disabled={stopping} onClick={endSession}>
            {stopping ? "Saving…" : "End session and save"}
          </button>
        </div>
      </div>
    </>
  );
}

function Metric({ label, value, unit, tone = "" }: {
  label: string; value: string; unit: string; tone?: string;
}) {
  return (
    <div className={`prod-metric ${tone}`}>
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      <div className="u">{unit}</div>
    </div>
  );
}
