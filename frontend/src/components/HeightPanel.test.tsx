import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HEIGHT_NOT_HOMED, HEIGHT_READY } from "../testFixtures";
import { HeightPanel } from "./HeightPanel";

type Call = [string, { body?: string } | undefined];

function mockFetch() {
  const fetch = vi.fn((_p: string, _i?: { body?: string }) =>
    Promise.resolve({ ok: true, json: async () => ({}) }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

function posted(fetch: ReturnType<typeof mockFetch>) {
  return (fetch.mock.calls as Call[]).map(([p, i]) => [p, i?.body ? JSON.parse(i.body) : null]);
}

it("will not offer a height until the deck knows where it is", () => {
  render(<HeightPanel height={HEIGHT_NOT_HOMED} />);

  expect(screen.getByText(/position is not known yet/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Home the deck" })).toBeEnabled();
  // No height controls at all: an absolute height would be meaningless.
  expect(screen.queryByRole("button", { name: "Raise" })).not.toBeInTheDocument();
});

it("warns that nobody should be on the deck while it homes", () => {
  render(<HeightPanel height={HEIGHT_NOT_HOMED} />);
  expect(screen.getByText(/Nobody should be on the deck/)).toBeInTheDocument();
});

it("raises and lowers in ten millimetre steps", async () => {
  const fetch = mockFetch();
  render(<HeightPanel height={HEIGHT_READY} />);

  fireEvent.click(screen.getByRole("button", { name: "Raise" }));
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(posted(fetch)[0]).toEqual(["/api/height/move", { steps: 1 }]);

  fireEvent.click(screen.getByRole("button", { name: "Lower" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(posted(fetch)[1]).toEqual(["/api/height/move", { steps: -1 }]);
});

it("accepts a height typed in and confirmed with Enter", async () => {
  const fetch = mockFetch();
  render(<HeightPanel height={HEIGHT_READY} />);

  const box = screen.getByLabelText(/mm/i, { selector: "input" });
  fireEvent.change(box, { target: { value: "450" } });
  fireEvent.keyDown(box, { key: "Enter" });

  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(posted(fetch)[0]).toEqual(["/api/height/move", { mm: 450 }]);
});

it("shows where the deck is set, and its travel", () => {
  render(<HeightPanel height={HEIGHT_READY} />);
  expect(screen.getByText("300")).toBeInTheDocument();
  expect(screen.getByText("20–750 mm")).toBeInTheDocument();
});

it("shows progress and a working Stop while the deck moves", () => {
  render(<HeightPanel height={{ ...HEIGHT_READY, moving: true, progress: 0.4, seconds_left: 12,
    can_move: false }} />);

  expect(screen.getByRole("status")).toHaveTextContent("about 12 s left");
  expect(screen.getByText(/Keep clear/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Raise" })).toBeDisabled();
});

it("locks the controls while a session records, and says why", () => {
  render(<HeightPanel height={{ ...HEIGHT_READY, locked_by_session: true, can_move: false }} />);

  expect(screen.getByText(/session is recording/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Raise" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Re-home" })).toBeDisabled();
});

it("says plainly when the console has no height control", () => {
  render(<HeightPanel height={{ ...HEIGHT_READY, available: false, backend: null }} />);
  expect(screen.getByText(/without belt-height control/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("surfaces a refusal from the backend", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: false, status: 409, json: async () => ({ detail: "The deck has not been homed yet." }),
  })));
  render(<HeightPanel height={HEIGHT_READY} />);

  fireEvent.click(screen.getByRole("button", { name: "Raise" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("not been homed");
});
