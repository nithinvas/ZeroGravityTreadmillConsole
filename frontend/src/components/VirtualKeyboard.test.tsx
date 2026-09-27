import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { VirtualKeyboard } from "./VirtualKeyboard";

/** A controlled input, the same shape every field in the app has. */
function Harness({ mode }: { mode?: "numeric" | "decimal" }) {
  const [value, setValue] = useState("");
  const [entered, setEntered] = useState(0);
  return (
    <>
      <input aria-label="field" inputMode={mode} value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && setEntered((n) => n + 1)} />
      <span data-testid="entered">{entered}</span>
      <VirtualKeyboard enabled />
    </>
  );
}

const tap = (name: string) => fireEvent.pointerDown(screen.getByRole("button", { name }));

it("stays hidden until a field is focused", () => {
  render(<Harness />);
  expect(screen.queryByRole("group", { name: "On-screen keyboard" })).not.toBeInTheDocument();

  fireEvent.focusIn(screen.getByLabelText("field"));
  expect(screen.getByRole("group", { name: "On-screen keyboard" })).toBeInTheDocument();
});

it("types into a React-controlled field", () => {
  // Setting .value directly would be invisible to React and the next render
  // would wipe it, so this is the assertion that matters most here.
  render(<Harness />);
  const field = screen.getByLabelText("field") as HTMLInputElement;
  fireEvent.focusIn(field);

  tap("a"); tap("b"); tap("1");
  expect(field.value).toBe("ab1");
});

it("shows a numeric pad for a numeric field, and no letters", () => {
  render(<Harness mode="decimal" />);
  fireEvent.focusIn(screen.getByLabelText("field"));

  expect(screen.getByRole("button", { name: "7" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "q" })).not.toBeInTheDocument();
});

it("backspaces and clears", () => {
  render(<Harness />);
  const field = screen.getByLabelText("field") as HTMLInputElement;
  fireEvent.focusIn(field);

  tap("a"); tap("b"); tap("c");
  tap("Backspace");
  expect(field.value).toBe("ab");
  tap("Clear");
  expect(field.value).toBe("");
});

it("shifts one letter at a time", () => {
  render(<Harness />);
  const field = screen.getByLabelText("field") as HTMLInputElement;
  fireEvent.focusIn(field);

  tap("Shift");
  // With shift held the keys themselves show uppercase, which is how the
  // operator knows it is on.
  tap("A");
  tap("b");
  expect(field.value).toBe("Ab");
});

it("enter reaches the field's own handler", () => {
  // The height entry applies on Enter, so this has to be a real key event.
  render(<Harness mode="numeric" />);
  fireEvent.focusIn(screen.getByLabelText("field"));

  tap("4"); tap("5"); tap("0");
  tap("Enter");
  expect(screen.getByTestId("entered")).toHaveTextContent("1");
});

it("done puts the keyboard away", () => {
  render(<Harness />);
  fireEvent.focusIn(screen.getByLabelText("field"));
  tap("Close keyboard");
  expect(screen.queryByRole("group", { name: "On-screen keyboard" })).not.toBeInTheDocument();
});

it("stays out of the way when it is switched off", () => {
  render(
    <>
      <input aria-label="field" />
      <VirtualKeyboard enabled={false} />
    </>,
  );
  fireEvent.focusIn(screen.getByLabelText("field"));
  expect(screen.queryByRole("group", { name: "On-screen keyboard" })).not.toBeInTheDocument();
});
