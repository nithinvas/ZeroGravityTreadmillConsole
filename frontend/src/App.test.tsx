import { act, render, screen } from "@testing-library/react";
import App from "./App";
import { HEIGHT_READY, NO_TREADMILL } from "./testFixtures";
import type { Snapshot } from "./types";

class FakeSocket {
  static instances: FakeSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  close() {
    this.onclose?.();
  }
}

const snapshot: Snapshot = {
  app: { version: "0.1.0", source: "usb", nominal_rate_hz: 976.5625 },
  link: { state: "streaming", detail: "", device: { product: "Load cell board", bcd_device: "0100" }, segment: 1, since_s: 3 },
  stream: {
    rate_hz: 976.4, packets_per_s: 244.1, session_rate_hz: 976.5, elapsed_s: 12, sample_period_us: 1024,
    last_data_age_s: 0.01, max_queue_depth: 2,
    counters: { transfers: 3000, bytes: 192000, samples: 12000, short_transfers: 0, out_of_range: 0, timeouts: 0, reconnects: 0, queue_overflows: 0 },
  },
  channels: [
    { name: "TL", last: 1, mean: 1, min: 0, max: 2, std: 1, noise: 1 },
    { name: "TR", last: 2, mean: 2, min: 0, max: 2, std: 1, noise: 1 },
    { name: "BR", last: 3, mean: 3, min: 0, max: 2, std: 1, noise: 1 },
    { name: "BL", last: 4, mean: 4, min: 0, max: 2, std: 1, noise: 1 },
  ],
  warnings: [{ code: "channels_identical", message: "All four channels show the same signal." }],
  recording: null,
  calibration: { status: "missing", message: "No calibration.", method: null, in_use: "none" },
  weight: null,
  capture_ready: true,
  simulator: null,
  treadmill: NO_TREADMILL,
  height: HEIGHT_READY,
  session: null,
};

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [] })));
});

afterEach(() => vi.unstubAllGlobals());

function liveSocket() {
  return FakeSocket.instances.find((s) => s.url.endsWith("/ws/live"))!;
}

it("shows streaming state, values and warnings from the live socket", async () => {
  render(<App />);
  await act(async () => {
    liveSocket().onopen?.();
    liveSocket().onmessage?.({ data: JSON.stringify(snapshot) });
  });
  await act(async () => screen.getByRole("button", { name: "Live signals" }).click());

  expect(screen.getByTestId("link-state")).toHaveTextContent("Streaming");
  expect(screen.getByText("All four channels show the same signal.")).toBeInTheDocument();
  expect(screen.getByText("976.40")).toBeInTheDocument();
});

it("says so when the backend connection drops, instead of showing stale values as live", async () => {
  render(<App />);
  await act(async () => {
    liveSocket().onopen?.();
    liveSocket().onmessage?.({ data: JSON.stringify(snapshot) });
  });
  await act(async () => liveSocket().close());

  expect(screen.getByTestId("link-state")).toHaveTextContent("Reconnecting to backend");
  expect(screen.getByRole("status")).toHaveTextContent("not updating");
});
