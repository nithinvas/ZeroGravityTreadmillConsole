import { useCallback, useEffect, useRef, useState } from "react";

/**
 * An on-screen keyboard for the touch panel.
 *
 * The appliance has no physical keyboard, so every field — a patient's name, a
 * belt height, a known weight — has to be typeable by hand on the screen.
 *
 * It docks at the bottom and follows focus: a numeric pad for numeric fields, a
 * full layout for text ones. Keys are driven on `pointerdown` with the default
 * prevented, so the focused field never loses focus to the key being pressed —
 * which would close the keyboard on the first tap.
 */

type Layout = "numeric" | "text";

const NUMERIC_ROWS = [
  ["1", "2", "3"],
  ["4", "5", "6"],
  ["7", "8", "9"],
  [".", "0", "-"],
];

const TEXT_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m", ",", "."],
];

type Field = HTMLInputElement | HTMLTextAreaElement;

function isTypable(el: Element | null): el is Field {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "TEXTAREA") return !(el as HTMLTextAreaElement).disabled;
  if (tag !== "INPUT") return false;
  const input = el as HTMLInputElement;
  if (input.disabled || input.readOnly) return false;
  return ["text", "number", "search", "tel", "email", ""].includes(input.type);
}

function layoutFor(el: Field): Layout {
  const mode = el.getAttribute("inputMode") ?? el.getAttribute("inputmode");
  if (mode === "numeric" || mode === "decimal") return "numeric";
  if (el.tagName === "INPUT" && (el as HTMLInputElement).type === "number") return "numeric";
  return "text";
}

/**
 * Writes into a React-controlled field.
 *
 * Setting `.value` directly is invisible to React — it tracks the previous
 * value on the DOM node and would decide nothing changed, so the next render
 * would put the old text straight back. Going through the prototype's setter
 * and then dispatching a real `input` event is what makes React see it.
 */
function setValue(el: Field, next: string) {
  const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  setter?.call(el, next);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

/** True on a touch screen. The kiosk is one; a developer's laptop is not. */
export function isTouchDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  return navigator.maxTouchPoints > 0;
}

export function VirtualKeyboard({ enabled }: { enabled: boolean }) {
  const [field, setField] = useState<Field | null>(null);
  const [layout, setLayout] = useState<Layout>("text");
  const [shift, setShift] = useState(false);
  const [numbers, setNumbers] = useState(false);
  const fieldRef = useRef<Field | null>(null);

  useEffect(() => {
    fieldRef.current = field;
  }, [field]);

  useEffect(() => {
    if (!enabled) {
      setField(null);
      return;
    }
    const onFocus = (e: FocusEvent) => {
      const target = e.target as Element | null;
      if (!isTypable(target)) return;
      setField(target);
      setLayout(layoutFor(target));
      setNumbers(false);
      // The keyboard covers the lower third; make sure the field is not under it.
      // Optional call: not every environment implements it, and failing to
      // scroll is never a reason to stop the keyboard appearing.
      window.setTimeout(() => target.scrollIntoView?.({ block: "center", behavior: "smooth" }), 50);
    };
    const onFocusOut = (e: FocusEvent) => {
      // A tap on a key does not move focus (pointerdown is prevented), so a
      // focusout here really is the operator leaving the field.
      if (!e.relatedTarget || !isTypable(e.relatedTarget as Element)) {
        window.setTimeout(() => {
          if (!isTypable(document.activeElement)) setField(null);
        }, 120);
      }
    };
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, [enabled]);

  const press = useCallback((key: string) => {
    const el = fieldRef.current;
    if (!el) return;
    if (key === "backspace") {
      setValue(el, el.value.slice(0, -1));
      return;
    }
    if (key === "clear") {
      setValue(el, "");
      return;
    }
    if (key === "space") {
      setValue(el, `${el.value} `);
      return;
    }
    if (key === "enter") {
      // Textareas take a newline; everything else treats Enter as "apply", and
      // the app's own onKeyDown handlers are listening for exactly this.
      if (el.tagName === "TEXTAREA") {
        setValue(el, `${el.value}\n`);
        return;
      }
      el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", bubbles: true }));
      return;
    }
    setValue(el, el.value + (shift ? key.toUpperCase() : key));
    if (shift) setShift(false);
  }, [shift]);

  if (!enabled || !field) return null;

  const rows = layout === "numeric" ? NUMERIC_ROWS : numbers ? [TEXT_ROWS[0]] : TEXT_ROWS;

  return (
    <div
      className={`keyboard ${layout}`}
      role="group"
      aria-label="On-screen keyboard"
      // Nothing inside may take focus away from the field being typed into.
      onPointerDown={(e) => e.preventDefault()}
    >
      <div className="keyboard-rows">
        {rows.map((row, i) => (
          <div className="keyboard-row" key={i}>
            {row.map((key) => (
              <button key={key} className="key" onPointerDown={(e) => { e.preventDefault(); press(key); }}>
                {shift && layout === "text" ? key.toUpperCase() : key}
              </button>
            ))}
          </div>
        ))}
        <div className="keyboard-row">
          {layout === "text" && (
            <>
              <button className="key wide" aria-label="Shift" aria-pressed={shift}
                onPointerDown={(e) => { e.preventDefault(); setShift(!shift); }}>⇧</button>
              <button className="key wide" aria-label="Numbers"
                onPointerDown={(e) => { e.preventDefault(); setNumbers(!numbers); }}>
                {numbers ? "abc" : "123"}
              </button>
              <button className="key space" aria-label="Space"
                onPointerDown={(e) => { e.preventDefault(); press("space"); }}>space</button>
            </>
          )}
          <button className="key wide" aria-label="Backspace"
            onPointerDown={(e) => { e.preventDefault(); press("backspace"); }}>⌫</button>
          <button className="key wide" aria-label="Clear"
            onPointerDown={(e) => { e.preventDefault(); press("clear"); }}>clear</button>
          <button className="key wide primary" aria-label="Enter"
            onPointerDown={(e) => { e.preventDefault(); press("enter"); }}>enter</button>
          <button className="key wide" aria-label="Close keyboard"
            onPointerDown={(e) => { e.preventDefault(); fieldRef.current?.blur(); setField(null); }}>
            done
          </button>
        </div>
      </div>
    </div>
  );
}
