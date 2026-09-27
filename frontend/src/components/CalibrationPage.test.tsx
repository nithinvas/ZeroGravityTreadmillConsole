import { act, fireEvent, render, screen } from "@testing-library/react";
import { CalibrationPage } from "./CalibrationPage";
import type { CalibrationInfo, Snapshot } from "../types";

const withDefaults: CalibrationInfo = {
  status: "missing",
  message: "No coefficients selected.",
  in_use: "none",
  active: null,
  defaults: {
    present: true,
    path: "/Users/x/TrendMill/calibration/defaults.json",
    zeros: [-553476.8, 405763.4, -549396.9, -63667.4],
    counts_per_kg: [-22442.38, -21816.8, -22406.59, -21849.17],
    firmware_bcd: "0100",
    saved_at: "2026-09-19T13:12:30+00:00",
    note: "",
  },
  history: [],
};
const withoutDefaults: CalibrationInfo = {
  ...withDefaults,
  defaults: { present: false, path: "/Users/x/TrendMill/calibration/defaults.json" },
};

const snapshot = {
  channels: [
    { name: "TL", last: 0, mean: -553476.8 - 22442.38 * 5, min: 0, max: 0, std: 0, noise: 0 },
    { name: "TR", last: 0, mean: 405763.4 - 21816.8 * 5, min: 0, max: 0, std: 0, noise: 0 },
    { name: "BR", last: 0, mean: -549396.9 - 22406.59 * 5, min: 0, max: 0, std: 0, noise: 0 },
    { name: "BL", last: 0, mean: -63667.4 - 21849.17 * 5, min: 0, max: 0, std: 0, noise: 0 },
  ],
  capture_ready: true,
} as unknown as Snapshot;

function serve(info: CalibrationInfo) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => ({ ok: true, json: async () => info }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
afterEach(() => vi.unstubAllGlobals());

it("says when default values are not present and offers to set them", async () => {
  serve(withoutDefaults);
  render(<CalibrationPage snapshot={snapshot} />);
  await act(async () => {});

  expect(screen.getByText("Default values not present.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save these values as defaults" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Load default values" })).toBeDisabled();
});

it("shows the defaults from the file and uses them on request", async () => {
  const fetchMock = serve(withDefaults);
  render(<CalibrationPage snapshot={snapshot} />);
  await act(async () => {});

  expect(screen.getByText("-22,442.38")).toBeInTheDocument();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Use default coefficients" }));
  });
  expect(fetchMock.mock.calls.some(([url]) => url === "/api/calibration/use-defaults")).toBe(true);
});

it("loads the default values into the form and previews the weight they give", async () => {
  serve(withDefaults);
  render(<CalibrationPage snapshot={snapshot} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "Load default values" }));

  expect(screen.getByLabelText("TL counts per kg")).toHaveValue("-22442.38");
  expect(screen.getByText("20.00 kg")).toBeInTheDocument(); // 5 kg on each cell
});

it("walks the four-corner steps in order", async () => {
  serve(withDefaults);
  render(<CalibrationPage snapshot={snapshot} />);
  await act(async () => {});

  expect(screen.getByText(/Step 1 of 5/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Capture tare" })).toBeEnabled();
});
