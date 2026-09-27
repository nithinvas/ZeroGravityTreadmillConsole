import { act, fireEvent, render, screen } from "@testing-library/react";
import { HoldButton, SessionPage } from "./SessionPage";
import { HEIGHT_READY, NO_TREADMILL, drivingAt } from "../testFixtures";
import type { SessionLive, Snapshot } from "../types";

class QuietSocket {
  onopen = null; onmessage = null; onclose = null; onerror = null;
  close() {}
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", QuietSocket);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) })));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const base = {
  calibration: { status: "ok", message: "", method: "defaults", in_use: "defaults" },
  treadmill: NO_TREADMILL,
  height: HEIGHT_READY,
  session: null,
} as unknown as Snapshot;

const live: SessionLive = {
  id: "20260919-183015-3f2a9c1e",
  details: { patient_name: "Asha Rao", patient_id: "P-014", issue: "", tester: "Nithin", speed_kph: 3,
    activity: "walk", body_weight_kg: null, bws_percent: null, incline_percent: null, notes: "" },
  elapsed_s: 95,
  condition: { id: 2, start_s: 60, speed_kph: 3.5, activity: "walk", bws_percent: null,
    incline_percent: null, note: "" },
  conditions: 2,
  gait: { state: "walking", cadence_spm: 104.8, step_length_m: 0.557, stride_length_m: 1.113, confidence: "high",
    prompt: null, steps_total: 150, steps_accepted: 146, front_kg: 30, amplitude_kg: 12 },
  walking_s: 84,
  distance_m: 78.4,
  recent_steps: [],
};

it("will not start a session without coefficients", () => {
  const snapshot = { ...base, calibration: { status: "missing", message: "", method: null, in_use: "none" } } as unknown as Snapshot;
  render(<SessionPage snapshot={snapshot} onOpenReport={() => {}} onCalibrate={() => {}} />);

  expect(screen.getByRole("button", { name: "Start session" })).toBeDisabled();
  expect(screen.getByText(/No coefficients are selected/)).toBeInTheDocument();
});

it("collects the session details", () => {
  render(<SessionPage snapshot={base} onOpenReport={() => {}} onCalibrate={() => {}} />);

  for (const label of ["Patient name", "Patient ID", "Tester", "Belt speed (km/h)", "Activity"]) {
    expect(screen.getByLabelText(label)).toBeInTheDocument();
  }
  expect(screen.getByRole("button", { name: "Start session" })).toBeEnabled();
});

it("shows cadence, step length and stride length while recording", () => {
  render(<SessionPage snapshot={{ ...base, session: live }} onOpenReport={() => {}} onCalibrate={() => {}} />);

  expect(screen.getByText("104.8")).toBeInTheDocument();
  expect(screen.getByText("0.56")).toBeInTheDocument();
  expect(screen.getByText("1.11")).toBeInTheDocument();
  expect(screen.getByText(/146 of 150 steps accepted/)).toBeInTheDocument();
  expect(screen.getByText(/Condition 2/)).toBeInTheDocument();
});

it("ends a session only after a one-second hold", () => {
  vi.useFakeTimers();
  const onConfirm = vi.fn();
  render(<HoldButton label="Hold to end session" onConfirm={onConfirm} />);
  const button = screen.getByRole("button", { name: "Hold to end session" });

  fireEvent.pointerDown(button);
  act(() => { vi.advanceTimersByTime(400); });
  fireEvent.pointerUp(button);
  expect(onConfirm).not.toHaveBeenCalled();

  fireEvent.pointerDown(button);
  act(() => { vi.advanceTimersByTime(1100); });
  expect(onConfirm).toHaveBeenCalledOnce();
});

it("fixes the starting speed at 1 km/h when the treadmill is driving", () => {
  const snapshot = { ...base, treadmill: { ...drivingAt(1.0), running: false, can_start: true } };
  render(<SessionPage snapshot={snapshot as Snapshot} onOpenReport={() => {}} onCalibrate={() => {}} />);

  // No typed speed to disagree with the belt.
  expect(screen.queryByLabelText("Belt speed (km/h)")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Starting belt speed")).toHaveValue("1.0 km/h");
  expect(screen.getByRole("button", { name: "Start session and belt" })).toBeEnabled();
});

it("offers to start without the belt only after the backend refuses", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: false, status: 409, json: async () => ({ detail: "The treadmill is not connected." }),
  })));
  render(<SessionPage snapshot={base} onOpenReport={() => {}} onCalibrate={() => {}} />);
  expect(screen.queryByRole("button", { name: "Start without belt control" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Start session" }));

  expect(await screen.findByRole("button", { name: "Start without belt control" })).toBeEnabled();
  expect(screen.getByRole("alert")).toHaveTextContent("not connected");
});

it("drives speed from the treadmill panel during a session, not from a text box", () => {
  const snapshot = { ...base, session: live, treadmill: drivingAt(3.5) };
  render(<SessionPage snapshot={snapshot as Snapshot} onOpenReport={() => {}} onCalibrate={() => {}} />);

  expect(screen.getByRole("button", { name: "Faster" })).toBeEnabled();
  expect(screen.queryByLabelText("Belt speed (km/h)")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Hold to stop the belt and end the session/ }))
    .toBeInTheDocument();
});

it("keeps the manual speed box when no treadmill is driving", () => {
  render(<SessionPage snapshot={{ ...base, session: live } as Snapshot}
    onOpenReport={() => {}} onCalibrate={() => {}} />);

  expect(screen.getByLabelText("Belt speed (km/h)")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Apply as new condition" })).toBeInTheDocument();
});
