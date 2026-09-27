import { act, fireEvent, render, screen } from "@testing-library/react";
import { SessionsPage } from "./SessionsPage";

const rows = [{
  id: "20260919-183015-3f2a9c1e", started_at: "2026-09-19T13:00:15+00:00", finished_at: "2026-09-19T13:10:15+00:00",
  status: "completed", patient_name: "Asha Rao", patient_id: "P-014", issue: "left knee", tester: "Nithin",
  activity: "walk", duration_s: 600, walking_s: 540, distance_m: 450, steps_accepted: 900, conditions: 2,
  speeds: "3, 3.5", main_cadence: 104.8, main_step_length: 0.557, main_stride_length: 1.113,
}];

afterEach(() => vi.unstubAllGlobals());

it("searches saved sessions and lists them", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn(async (_url: string) => ({ ok: true, json: async () => rows }));
  vi.stubGlobal("fetch", fetchMock);
  const onOpen = vi.fn();
  render(<SessionsPage openId={null} onOpen={onOpen} />);
  fireEvent.change(screen.getByLabelText("Search sessions"), { target: { value: "asha" } });
  await act(async () => { vi.advanceTimersByTime(300); });
  vi.useRealTimers();
  await act(async () => {});

  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("q=asha"))).toBe(true);
  expect(screen.getByText("Asha Rao")).toBeInTheDocument();
  expect(screen.getByText("104.8 /min")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Asha Rao"));
  expect(onOpen).toHaveBeenCalledWith("20260919-183015-3f2a9c1e");
});
