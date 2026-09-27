import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NO_TREADMILL, drivingAt } from "../testFixtures";
import type { TreadmillState } from "../types";
import { TreadmillPanel } from "./TreadmillPanel";

type Call = [string, { body?: string } | undefined];

function mockFetch() {
  const fetch = vi.fn((_path: string, _init?: { body?: string }) =>
    Promise.resolve({ ok: true, json: async () => ({}) }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

/** What was actually sent, so the assertions read like the wire. */
/** Connected and in control, belt stopped: no speed, and none settable. */
function stoppedBelt() {
  return {
    ...drivingAt(4.5), running: false, can_start: true, can_stop: false,
    can_change_speed: false, target_speed_kph: null, reported_speed_kph: 0,
  };
}

function posted(fetch: ReturnType<typeof mockFetch>) {
  return (fetch.mock.calls as Call[]).map(([path, init]) => [
    path,
    init?.body ? JSON.parse(init.body) : null,
  ]);
}

it("offers a connection check and says plainly that nothing is connected", () => {
  render(<TreadmillPanel treadmill={NO_TREADMILL} />);

  // The status pill and the detail line both say it: one glance, one read.
  expect(screen.getAllByText("Not connected")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Check connection" })).toBeEnabled();
  // No belt buttons at all until there is a belt to drive.
  expect(screen.queryByRole("button", { name: "Start belt" })).not.toBeInTheDocument();
});

it("shows why a connection failed rather than just the word failed", () => {
  const failed: TreadmillState = {
    ...NO_TREADMILL,
    state: "failed",
    detail: "No treadmill found. Check it is switched on, within range.",
  };
  render(<TreadmillPanel treadmill={failed} />);

  expect(screen.getByText(/Check it is switched on/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
});

it("greys out Start while the belt is running, and Stop while it is stopped", () => {
  const { rerender } = render(<TreadmillPanel treadmill={drivingAt(4.5)} />);
  expect(screen.getByRole("button", { name: "Start belt" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Stop belt" })).toBeEnabled();

  rerender(<TreadmillPanel treadmill={stoppedBelt()} />);
  expect(screen.getByRole("button", { name: "Start belt" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Stop belt" })).toBeDisabled();
});

it("shows no speed at all while the belt is stopped, and will not change one", () => {
  // The treadmill has no 0 km/h: stopped means no speed, and Start comes up at 1.
  render(<TreadmillPanel treadmill={stoppedBelt()} />);

  expect(screen.getByRole("button", { name: "Faster" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Slower" })).toBeDisabled();
  expect(screen.queryByText("4.5")).not.toBeInTheDocument();
  expect(screen.getByText(/Start brings it up at 1.0 km\/h/)).toBeInTheDocument();
});

it("steps the speed by the machine's own increment", async () => {
  const fetch = mockFetch();
  render(<TreadmillPanel treadmill={drivingAt(3.0)} />);

  fireEvent.click(screen.getByRole("button", { name: "Faster" }));
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(posted(fetch)[0]).toEqual(["/api/treadmill/speed", { steps: 1 }]);

  fireEvent.click(screen.getByRole("button", { name: "Slower" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(posted(fetch)[1]).toEqual(["/api/treadmill/speed", { steps: -1 }]);
});

it("steps the incline too", async () => {
  const fetch = mockFetch();
  render(<TreadmillPanel treadmill={drivingAt(3.0)} />);

  fireEvent.click(screen.getByRole("button", { name: "More incline" }));
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(posted(fetch)[0]).toEqual(["/api/treadmill/incline", { steps: 1 }]);
});

it("shows the target and the belt's own reading side by side", () => {
  // The belt lags the target while the motor ramps; hiding that makes the console
  // look wrong when it is right.
  const ramping = { ...drivingAt(6.0), reported_speed_kph: 4.2 };
  render(<TreadmillPanel treadmill={ramping} />);

  expect(screen.getAllByText("6.0").length).toBeGreaterThan(0);
  expect(screen.getByText("belt 4.2")).toBeInTheDocument();
  expect(screen.getByText("Running")).toBeInTheDocument();
});

it("raises the safety key rather than leaving it in the log", () => {
  const pulled = { ...drivingAt(3.0), running: false, can_start: true, can_stop: false,
    safety_key_pulled: true };
  render(<TreadmillPanel treadmill={pulled} />);

  expect(screen.getByText(/safety key was pulled/i)).toBeInTheDocument();
});

it("explains itself when the console has no treadmill support at all", () => {
  render(<TreadmillPanel treadmill={{ ...NO_TREADMILL, available: false, backend: null }} />);

  expect(screen.getByText(/without treadmill control/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("surfaces a refused command instead of silently doing nothing", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: false,
    status: 409,
    json: async () => ({ detail: "Set speed — Control was not granted" }),
  })));
  render(<TreadmillPanel treadmill={drivingAt(3.0)} />);

  fireEvent.click(screen.getByRole("button", { name: "Faster" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Control was not granted");
});

it("will not let a disconnected machine be commanded", () => {
  const connectedNoControl = { ...drivingAt(3.0), has_control: false, can_start: false,
    can_stop: false, can_change_speed: false };
  render(<TreadmillPanel treadmill={connectedNoControl} />);

  expect(screen.getByRole("button", { name: "Faster" })).toBeDisabled();
  expect(screen.getByText(/has not granted control/)).toBeInTheDocument();
});
