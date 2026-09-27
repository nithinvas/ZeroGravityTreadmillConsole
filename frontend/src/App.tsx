import { useCallback, useState } from "react";
import { CalibrationPage } from "./components/CalibrationPage";
import { ChannelGrid } from "./components/ChannelGrid";
import { HeightPanel } from "./components/HeightPanel";
import { RecordingPanel } from "./components/RecordingPanel";
import { SessionPage } from "./components/SessionPage";
import { SessionsPage } from "./components/SessionsPage";
import { SimulatorPanel } from "./components/SimulatorPanel";
import { StreamStats } from "./components/StreamStats";
import { VirtualKeyboard, isTouchDevice } from "./components/VirtualKeyboard";
import { Warnings } from "./components/Warnings";
import { WeightPage } from "./components/WeightPage";
import type { Channel, Snapshot } from "./types";
import { useSocket } from "./useSocket";

type Tab = "session" | "sessions" | "live" | "weight" | "height" | "calibration";
const TABS: [Tab, string][] = [
  ["session", "Session"],
  ["sessions", "Sessions"],
  ["live", "Live signals"],
  ["weight", "Weight"],
  ["height", "Belt height"],
  ["calibration", "Calibration"],
];

const STATE_TEXT: Record<string, string> = {
  streaming: "Streaming",
  waiting: "Waiting for board",
  disconnected: "Disconnected",
  stopped: "Stopped",
};

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [zero, setZero] = useState<Partial<Record<Channel["name"], number>>>({});
  const [tab, setTab] = useState<Tab>("session");
  // On the kiosk there is no physical keyboard, so it is on by default there.
  // On a developer's laptop it would only be in the way, hence the toggle.
  const [keyboard, setKeyboard] = useState(() => {
    try {
      const saved = localStorage.getItem("treadmill.keyboard");
      if (saved !== null) return saved === "on";
    } catch {
      // private mode, or storage blocked: fall back to the device
    }
    return isTouchDevice();
  });
  const toggleKeyboard = () => {
    setKeyboard((on) => {
      try {
        localStorage.setItem("treadmill.keyboard", on ? "off" : "on");
      } catch {
        // not being able to remember the choice is not a reason to refuse it
      }
      return !on;
    });
  };
  const [reportId, setReportId] = useState<string | null>(null);
  const openReport = (id: string | null) => {
    setReportId(id);
    setTab("sessions");
  };
  const onMessage = useCallback((s: Snapshot) => setSnapshot(s), []);
  const socket = useSocket<Snapshot>("/ws/live", onMessage);

  const live = socket === "open" && snapshot !== null;
  const state = live ? snapshot.link.state : "reconnecting";
  const device = snapshot?.link.device ?? {};

  const zeroAll = () => {
    if (!snapshot) return;
    const next: Partial<Record<Channel["name"], number>> = {};
    for (const c of snapshot.channels) if (c.mean !== null) next[c.name] = c.mean;
    setZero(next);
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>TreadMill <span className="muted">Console</span></h1>
        <div className={`pill pill-${state}`} data-testid="link-state">
          {live ? STATE_TEXT[state] ?? state : socket === "connecting" ? "Connecting" : "Reconnecting to backend"}
        </div>
        <button className={`kbd-toggle${keyboard ? " on" : ""}`} onClick={toggleKeyboard}
          aria-pressed={keyboard} title="On-screen keyboard">⌨</button>
        {snapshot && (
          <div className="device muted">
            {snapshot.app.source}
            {device.product ? ` · ${device.product}` : ""}
            {device.bcd_device ? ` · fw ${device.bcd_device}` : ""}
            {` · v${snapshot.app.version}`}
          </div>
        )}
      </header>

      {!live && (
        <div className="stale" role="status">
          No live connection to the backend. Values below are not updating.
        </div>
      )}

      <nav className="tabs" aria-label="Screens">
        {TABS.map(([id, label]) => (
          <button key={id} className={`tab${tab === id ? " selected" : ""}`} onClick={() => setTab(id)}
            aria-current={tab === id ? "page" : undefined}>
            {label}
            {id === "session" && snapshot?.session && <span className="rec-dot inline" aria-label="recording" />}
          </button>
        ))}
      </nav>

      {snapshot && (
        <main className={live ? "" : "is-stale"}>
          <Warnings warnings={snapshot.warnings} />
          <div className={`columns${tab === "sessions" ? " single" : ""}`}>
            <div className="col-main">
              {tab === "live" && (
                <>
                  <ChannelGrid
                    channels={snapshot.channels}
                    zero={zero}
                    onZero={zeroAll}
                    onClearZero={() => setZero({})}
                  />
                  <RecordingPanel active={snapshot.recording} />
                </>
              )}
              {tab === "session" && (
                <SessionPage snapshot={snapshot} onOpenReport={openReport} onCalibrate={() => setTab("calibration")} />
              )}
              {tab === "sessions" && <SessionsPage openId={reportId} onOpen={setReportId} />}
              {tab === "weight" && <WeightPage snapshot={snapshot} onCalibrate={() => setTab("calibration")} />}
              {tab === "height" && <HeightPanel height={snapshot.height} />}
              {tab === "calibration" && <CalibrationPage snapshot={snapshot} />}
            </div>
            <div className="col-side" hidden={tab === "sessions"}>
              {snapshot.simulator && <SimulatorPanel mode={snapshot.simulator} />}
              <StreamStats snapshot={snapshot} />
            </div>
          </div>
        </main>
      )}
      <VirtualKeyboard enabled={keyboard} />
    </div>
  );
}
