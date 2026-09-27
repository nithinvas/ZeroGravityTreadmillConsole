import { fireEvent, render, screen } from "@testing-library/react";
import { WeightPage } from "./WeightPage";
import { HEIGHT_READY, NO_TREADMILL } from "../testFixtures";
import type { Snapshot } from "../types";

function snapshot(overrides: Partial<Snapshot>): Snapshot {
  return {
    app: { version: "0.1.0", source: "usb", nominal_rate_hz: 976.5625 },
    link: { state: "streaming", detail: "", device: {}, segment: 1, since_s: 1 },
    stream: {
      rate_hz: 976, packets_per_s: 244, session_rate_hz: 976, elapsed_s: 5, sample_period_us: 1024,
      last_data_age_s: 0, max_queue_depth: 1,
      counters: { transfers: 1, bytes: 64, samples: 4, short_transfers: 0, out_of_range: 0, timeouts: 0, reconnects: 0, queue_overflows: 0 },
    },
    channels: [],
    warnings: [],
    recording: null,
    calibration: { status: "ok", message: "", method: "defaults", in_use: "defaults" },
    treadmill: NO_TREADMILL,
    height: HEIGHT_READY,
    weight: {
      live_kg: 58.04, average_kg: 57.98, std_kg: 0.1, stable: true,
      cells_kg: [13.54, 13.94, 0.94, 29.58], raw: [-561790, 75651, 692717, -74546], window_s: 2,
    },
    capture_ready: true,
    simulator: null,
    session: null,
    ...overrides,
  };
}

it("shows the live weight, average and stability", () => {
  render(<WeightPage snapshot={snapshot({})} onCalibrate={() => {}} />);

  expect(screen.getByTestId("live-weight")).toHaveTextContent("58.04");
  expect(screen.getByText("57.98 kg")).toBeInTheDocument();
  expect(screen.getByText("Stable reading")).toBeInTheDocument();
  expect(screen.getByText("29.58 kg")).toBeInTheDocument();
});

it("asks for a calibration instead of showing a number when there is none", () => {
  const onCalibrate = vi.fn();
  render(
    <WeightPage
      snapshot={snapshot({ calibration: { status: "missing", message: "No calibration.", method: null, in_use: "none" }, weight: null })}
      onCalibrate={onCalibrate}
    />,
  );

  expect(screen.queryByTestId("live-weight")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /calibrate/i }));
  expect(onCalibrate).toHaveBeenCalledOnce();
});

it("warns when the calibration was made on different firmware", () => {
  render(
    <WeightPage
      snapshot={snapshot({ calibration: { status: "firmware_mismatch", message: "Made on firmware 0100.", method: "manual", in_use: "custom" } })}
      onCalibrate={() => {}}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent("Made on firmware 0100.");
});
