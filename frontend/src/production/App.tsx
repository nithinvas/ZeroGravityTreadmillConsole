import { useCallback, useState } from "react";
import EngineeringConsole from "../App";
import { postJson } from "../api";
import type { Snapshot } from "../types";
import { useSocket } from "../useSocket";
import { HomeScreen, type Patient } from "./HomeScreen";
import { LockScreen, type Staff } from "./LockScreen";
import { ReportScreen } from "./ReportScreen";
import { SessionScreen } from "./SessionScreen";
import { StaffScreen } from "./StaffScreen";
import { TopBar } from "./parts";
import { Wizard, type WizardResult } from "./Wizard";
import "./theme.css";

/**
 * The production console.
 *
 * One screen at a time, in the order a session actually happens: sign in, pick
 * or register a patient, work through the checks, walk, read the report. The
 * engineering console we built first is still here behind a technician-only
 * door — it is how the machine gets calibrated and diagnosed, and it stays the
 * fallback while this is new.
 */

type Screen =
  | { at: "lock" }
  | { at: "home" }
  | { at: "wizard"; patient: Patient | null }
  | { at: "session"; bws: number }
  | { at: "report"; id: string }
  | { at: "staff" }
  | { at: "service" };

export default function ProductionApp() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [staff, setStaff] = useState<Staff | null>(null);
  const [screen, setScreen] = useState<Screen>({ at: "lock" });
  const onMessage = useCallback((s: Snapshot) => setSnapshot(s), []);
  const socket = useSocket<Snapshot>("/ws/live", onMessage);

  // Stopping the belt must work from anywhere, including the lock screen.
  const stopBelt = () => void postJson("/api/treadmill/stop").catch(() => undefined);

  // A session already running when the screen loads — after a reload, or a
  // browser that was restarted mid-session — must be picked up, not lost.
  if (snapshot?.session && screen.at !== "session" && screen.at !== "service"
      && screen.at !== "staff" && staff) {
    setScreen({ at: "session", bws: 0 });
  }

  if (screen.at === "service") {
    return (
      <div style={{ position: "fixed", inset: 0, overflow: "auto" }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 14, padding: "8px 16px",
          background: "#111820", borderBottom: "1px solid #1f2c38", color: "#e8f0f7",
          font: "14px system-ui",
        }}>
          <strong>Service console</strong>
          <span style={{ color: "#7e8fa0", fontSize: 12.5 }}>
            Calibration, diagnostics and the raw signal. Everything here affects every measurement.
          </span>
          <button style={{
            marginLeft: "auto", background: "#19e5a5", border: "none", color: "#062018",
            borderRadius: 8, padding: "8px 16px", fontWeight: 700, cursor: "pointer",
          }} onClick={() => setScreen({ at: "home" })}>
            ← Back to the console
          </button>
        </div>
        <EngineeringConsole />
      </div>
    );
  }

  const technicianTools = staff?.role === "technician" && screen.at !== "session" ? (
    <>
      <button className="prod-btn ghost" onClick={() => setScreen({ at: "staff" })}>Staff</button>
      <button className="prod-btn ghost" onClick={() => setScreen({ at: "service" })}>Service</button>
    </>
  ) : null;

  return (
    <div className="prod">
      <TopBar snapshot={snapshot} right={
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {technicianTools}
          {staff && screen.at !== "session" && (
            <button className="prod-btn ghost" onClick={() => { setStaff(null); setScreen({ at: "lock" }); }}>
              {staff.name} · Sign out
            </button>
          )}
        </div>
      } />

      <div className="prod-body">
        {socket !== "open" && (
          <div className="prod-error" style={{ margin: 18 }}>
            No live connection to the console. Values are not updating.
          </div>
        )}

        {screen.at === "lock" && (
          <LockScreen
            onSignedIn={(who) => { setStaff(who); setScreen({ at: "home" }); }}
            onStopEverything={stopBelt}
          />
        )}

        {screen.at === "home" && (
          <HomeScreen
            onNewPatient={() => setScreen({ at: "wizard", patient: null })}
            onPickPatient={(p) => setScreen({ at: "wizard", patient: p })}
            onManageStaff={staff?.role === "technician" ? () => setScreen({ at: "staff" }) : undefined}
            onService={staff?.role === "technician" ? () => setScreen({ at: "service" }) : undefined}
          />
        )}

        {screen.at === "wizard" && snapshot && staff && (
          <Wizard
            snapshot={snapshot}
            staff={staff}
            patient={screen.patient}
            onCancel={() => setScreen({ at: "home" })}
            onStart={(r) => void startSession(r, setScreen)}
          />
        )}

        {screen.at === "session" && snapshot?.session && (
          <SessionScreen
            snapshot={snapshot}
            session={snapshot.session}
            bwsPercent={screen.bws}
            onFinished={(id) => setScreen({ at: "report", id })}
          />
        )}

        {screen.at === "session" && !snapshot?.session && (
          <div className="prod-empty">
            No session is running.{" "}
            <button className="prod-btn" onClick={() => setScreen({ at: "home" })}>Back to home</button>
          </div>
        )}

        {screen.at === "staff" && staff && (
          <StaffScreen me={staff} onDone={() => setScreen({ at: "home" })} />
        )}

        {screen.at === "report" && (
          <ReportScreen id={screen.id} onDone={() => setScreen({ at: "home" })} />
        )}
      </div>
    </div>
  );
}

async function startSession(r: WizardResult, setScreen: (s: Screen) => void) {
  await postJson("/api/sessions", {
    patient_name: r.patient.name,
    patient_id: r.patient.id,
    issue: r.patient.diagnosis,
    tester: "",
    body_weight_kg: r.patient.weight_kg,
    bws_percent: r.bwsPercent || null,
    // Started without belt control when no treadmill is connected: the load
    // cells and gait still record, which is most of the value.
    without_treadmill: true,
  });
  setScreen({ at: "session", bws: r.bwsPercent });
}
