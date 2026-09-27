import { fireEvent, render, screen, within } from "@testing-library/react";
import { ChannelGrid } from "./ChannelGrid";
import type { Channel } from "../types";

function channel(name: Channel["name"], mean: number): Channel {
  return { name, last: mean, mean, min: mean - 10, max: mean + 10, std: 5, noise: 20 };
}

const idle = [channel("TL", -536660), channel("TR", 101508), channel("BR", 694467), channel("BL", -19659)];

it("lays the cells out as they sit on the deck", () => {
  render(<ChannelGrid channels={idle} zero={{}} onZero={() => {}} onClearZero={() => {}} />);

  const names = screen.getAllByText(/^(TL|TR|BL|BR)$/).map((el) => el.textContent);
  expect(names).toEqual(["TL", "TR", "BL", "BR"]);
});

it("shows each cell's own raw value", () => {
  render(<ChannelGrid channels={idle} zero={{}} onZero={() => {}} onClearZero={() => {}} />);

  expect(within(screen.getByTestId("cell-BR")).getByLabelText("BR raw value")).toHaveTextContent("694,467");
  expect(within(screen.getByTestId("cell-TL")).getByLabelText("TL raw value")).toHaveTextContent("-536,660");
});

it("highlights only the pressed corner after zeroing", () => {
  const zero = { TL: -536660, TR: 101508, BR: 694467, BL: -19659 };
  const pressedTR = [channel("TL", -536600), channel("TR", 60000), channel("BR", 694400), channel("BL", -19600)];
  render(<ChannelGrid channels={pressedTR} zero={zero} onZero={() => {}} onClearZero={() => {}} />);

  expect(screen.getByTestId("cell-TR")).toHaveClass("active");
  expect(screen.getByTestId("cell-TL")).not.toHaveClass("active");
  expect(within(screen.getByTestId("cell-TR")).getByText("-41,508")).toBeInTheDocument();
});

it("calls onZero when Zero all is tapped", () => {
  const onZero = vi.fn();
  render(<ChannelGrid channels={idle} zero={{}} onZero={onZero} onClearZero={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Zero all" }));

  expect(onZero).toHaveBeenCalledOnce();
});
