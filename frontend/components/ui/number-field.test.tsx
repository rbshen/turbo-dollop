// @vitest-environment jsdom
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NumberField, type NumberFieldProps } from "@/components/ui/number-field";
import { FormField } from "@/components/ui/form-field";

afterEach(cleanup);

// A controlled harness: the parent owns the raw text, as every form will.
function Harness({
  initial = "30",
  onValue,
  ...props
}: { initial?: string; onValue?: (v: string) => void } & Partial<Omit<NumberFieldProps, "value" | "onChange">>) {
  const [value, setValue] = useState(initial);
  return (
    <NumberField
      id="nf"
      aria-label="Weeks"
      value={value}
      onChange={(v) => {
        setValue(v);
        onValue?.(v);
      }}
      {...props}
    />
  );
}

const box = () => screen.getByLabelText("Weeks") as HTMLInputElement;

describe("NumberField: input shape", () => {
  it("is a typed text input, not a native number input", () => {
    render(<Harness />);
    expect(box()).toHaveAttribute("type", "text");
    expect(box()).toHaveAttribute("inputmode", "decimal");
    expect(box()).toHaveClass("font-mono", "tabular-nums", "h-9");
  });

  it("reports the typed text and its validation to onChange, without altering it", () => {
    const onChange = vi.fn();
    render(<NumberField id="nf" aria-label="Weeks" value="1" onChange={onChange} integer min={2} max={200} />);
    fireEvent.change(box(), { target: { value: "1000" } });
    expect(onChange).toHaveBeenCalledWith("1000", { value: 1000, error: "Enter a value between 2 and 200." });
  });
});

describe("NumberField: keyboard", () => {
  it("steps up and down with the arrow keys", () => {
    render(<Harness initial="30" step={1} />);
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("31");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(box().value).toBe("29");
  });

  it("steps by ten times the step with Shift", () => {
    render(<Harness initial="30" step={0.5} />);
    fireEvent.keyDown(box(), { key: "ArrowUp", shiftKey: true });
    expect(box().value).toBe("35");
    fireEvent.keyDown(box(), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(box(), { key: "ArrowDown", shiftKey: true });
    expect(box().value).toBe("25");
  });

  it("handles decimal steps without float error", () => {
    render(<Harness initial="1.1" step={0.1} />);
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("1.2");
  });

  it("prevents the default caret jump on arrow keys", () => {
    render(<Harness />);
    expect(fireEvent.keyDown(box(), { key: "ArrowUp" })).toBe(false);
  });

  it("stops stepping at max and min", () => {
    render(<Harness initial="49" max={50} min={2} />);
    fireEvent.keyDown(box(), { key: "ArrowUp", shiftKey: true });
    expect(box().value).toBe("50");
    fireEvent.change(box(), { target: { value: "3" } });
    fireEvent.keyDown(box(), { key: "ArrowDown", shiftKey: true });
    expect(box().value).toBe("2");
  });

  it("does not step an invalid value (it leaves the text alone)", () => {
    const onValue = vi.fn();
    render(<Harness initial="abc" onValue={onValue} />);
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("abc");
    expect(onValue).not.toHaveBeenCalled();
  });

  it("does not step an out-of-range value either", () => {
    render(<Harness initial="500" max={200} />);
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(box().value).toBe("500");
  });

  it("rejects the letter e (either case) and lets other keys through", () => {
    render(<Harness />);
    expect(fireEvent.keyDown(box(), { key: "e" })).toBe(false);
    expect(fireEvent.keyDown(box(), { key: "E" })).toBe(false);
    expect(fireEvent.keyDown(box(), { key: "5" })).toBe(true);
    expect(fireEvent.keyDown(box(), { key: "Backspace" })).toBe(true);
    expect(fireEvent.keyDown(box(), { key: "a", ctrlKey: true })).toBe(true);
  });

  it("calls a caller's onKeyDown too", () => {
    const onKeyDown = vi.fn();
    render(<Harness onKeyDown={onKeyDown} />);
    fireEvent.keyDown(box(), { key: "5" });
    expect(onKeyDown).toHaveBeenCalledTimes(1);
  });

  it("does nothing when disabled", () => {
    render(<Harness initial="30" disabled />);
    expect(box()).toBeDisabled();
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("30");
  });
});

describe("NumberField: validation and error state", () => {
  it("shows no error and no invalid style for a valid value", () => {
    render(<Harness initial="30" integer min={2} max={200} />);
    expect(box()).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(box()).not.toHaveClass("border-negative");
  });

  it.each([
    ["abc", "Enter a number."],
    ["", "Enter a number."],
    ["2.5", "Enter a whole number."],
    ["1", "Enter a value between 2 and 200."],
    ["201", "Enter a value between 2 and 200."],
  ])("shows an inline error for %j", (text, message) => {
    render(<Harness initial={text} integer min={2} max={200} />);
    expect(box()).toHaveAttribute("aria-invalid", "true");
    expect(box()).toHaveClass("border-negative");
    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });

  it("never clamps or corrects what was typed", () => {
    render(<Harness initial="30" min={2} max={200} />);
    fireEvent.change(box(), { target: { value: "9999" } });
    fireEvent.blur(box());
    expect(box().value).toBe("9999");
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("links the error to the field with aria-describedby", () => {
    render(<Harness initial="abc" />);
    const alert = screen.getByRole("alert");
    expect(box().getAttribute("aria-describedby")).toContain(alert.id);
  });

  it("shows an external error and the invalid style even when the text is valid", () => {
    render(<Harness initial="30" error="Must be below the slow length." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Must be below the slow length.");
    expect(box()).toHaveAttribute("aria-invalid", "true");
  });

  it("honours an explicit invalid prop", () => {
    render(<Harness initial="30" invalid />);
    expect(box()).toHaveAttribute("aria-invalid", "true");
    expect(box()).toHaveClass("border-negative");
  });

  it("shows no validation of its own while disabled", () => {
    render(<Harness initial="abc" disabled />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(box()).not.toHaveAttribute("aria-invalid");
  });
});

describe("NumberField: sizes, unit and aria", () => {
  it.each([
    ["short", "w-24"],
    ["medium", "w-44"],
    ["wide", "w-80"],
    ["full", "w-full"],
  ] as const)("size %s uses %s, 36px high and capped at the container", (size, cls) => {
    render(<Harness size={size} />);
    expect(box()).toHaveClass(cls, "h-9");
    if (size !== "full") expect(box()).toHaveClass("max-w-full");
  });

  it("defaults to the short token", () => {
    render(<Harness />);
    expect(box()).toHaveClass("w-24");
  });

  it("renders the unit after the field and describes the field with it", () => {
    render(<Harness unit="weeks" />);
    const unit = screen.getByText("weeks");
    expect(box().compareDocumentPosition(unit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(box().getAttribute("aria-describedby")).toContain(unit.id);
  });

  it("passes aria attributes through and merges aria-describedby", () => {
    render(<Harness aria-describedby="outside" unit="weeks" aria-label="Weeks" />);
    expect(box().getAttribute("aria-describedby")).toMatch(/^outside /);
  });

  it("forwards its ref to the input", () => {
    let el: HTMLInputElement | null = null;
    render(<NumberField ref={(node) => { el = node; }} id="r" aria-label="x" value="1" onChange={() => {}} />);
    expect(el).toBe(screen.getByLabelText("x"));
  });
});

describe("NumberField: stepper", () => {
  it("is off by default: no buttons", () => {
    render(<Harness />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("joins 32px minus and plus buttons to the field's edges when on", () => {
    render(<Harness stepper />);
    const minus = screen.getByRole("button", { name: "Decrease" });
    const plus = screen.getByRole("button", { name: "Increase" });
    expect(minus).toHaveClass("w-8", "h-9", "rounded-l-md", "border-r-0");
    expect(plus).toHaveClass("w-8", "h-9", "rounded-r-md", "border-l-0");
    expect(box()).toHaveClass("rounded-none", "text-center");
    expect(minus.nextElementSibling).toBe(box());
    expect(box().nextElementSibling).toBe(plus);
  });

  it("steps with the buttons and by ten with Shift-click", () => {
    render(<Harness stepper initial="30" />);
    fireEvent.click(screen.getByRole("button", { name: "Increase" }));
    expect(box().value).toBe("31");
    fireEvent.click(screen.getByRole("button", { name: "Decrease" }), { shiftKey: true });
    expect(box().value).toBe("21");
  });

  it("disables a button at its bound, and both when the value is invalid or the field disabled", () => {
    const { rerender } = render(<Harness stepper initial="50" max={50} min={0} />);
    expect(screen.getByRole("button", { name: "Increase" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Decrease" })).toBeEnabled();
    rerender(<Harness stepper initial="abc" key="bad" />);
    expect(screen.getByRole("button", { name: "Decrease" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Increase" })).toBeDisabled();
    rerender(<Harness stepper initial="5" disabled key="dis" />);
    expect(screen.getByRole("button", { name: "Increase" })).toBeDisabled();
  });

  it("keeps the buttons out of the Tab order (arrows are the keyboard route)", () => {
    render(<Harness stepper />);
    expect(screen.getByRole("button", { name: "Increase" })).toHaveAttribute("tabindex", "-1");
  });
});

describe("NumberField inside a FormField", () => {
  it("takes its id from the field, so the label names it", () => {
    render(
      <FormField label="MA length" htmlFor="ma">
        <NumberField value="30" onChange={() => {}} />
      </FormField>,
    );
    expect(screen.getByLabelText("MA length")).toHaveAttribute("id", "ma");
  });

  it("describes itself with the hint, and shows the field's error once (not twice)", () => {
    render(
      <FormField label="MA length" htmlFor="ma" hint="Weeks in the average." error="Enter a whole number.">
        <NumberField value="2.5" integer onChange={() => {}} />
      </FormField>,
    );
    const input = screen.getByLabelText("MA length");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    const describedBy = input.getAttribute("aria-describedby") ?? "";
    expect(describedBy).toContain("ma-hint");
    expect(describedBy).toContain("ma-error");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("falls back to its own message if the field was given no error, so nothing is silent", () => {
    render(
      <FormField label="MA length" htmlFor="ma">
        <NumberField value="abc" onChange={() => {}} />
      </FormField>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
  });
});

const SUFFIXES = { T: 1e12, B: 1e9, M: 1e6 };

describe("NumberField: optional", () => {
  it("treats empty as valid: no error, no invalid style, and onChange reports a null value", () => {
    const onChange = vi.fn();
    render(<NumberField id="nf" aria-label="Weeks" value="5" onChange={onChange} optional />);
    fireEvent.change(box(), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith("", { value: null, error: null });
  });

  it("shows no error for an empty optional field, and still errors on junk", () => {
    const { rerender } = render(<NumberField id="nf" aria-label="Weeks" value="" onChange={() => {}} optional />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(box()).not.toHaveAttribute("aria-invalid");
    rerender(<NumberField id="nf" aria-label="Weeks" value="abc" onChange={() => {}} optional />);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
  });

  it("keeps the default: an empty field is an error without optional", () => {
    render(<NumberField id="nf" aria-label="Weeks" value="" onChange={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
  });
});

describe("NumberField: suffixes", () => {
  it.each([
    ["500M", 500_000_000],
    ["2B", 2_000_000_000],
    ["1T", 1_000_000_000_000],
    ["1.", 1],
    [".5", 0.5],
  ])("reports %s as %d in base units, leaving the typed text alone", (text, value) => {
    const onChange = vi.fn();
    render(<NumberField id="nf" aria-label="Weeks" value="" onChange={onChange} suffixes={SUFFIXES} optional />);
    fireEvent.change(box(), { target: { value: text } });
    expect(onChange).toHaveBeenCalledWith(text, { value, error: null });
  });

  it.each([["5e"], ["1BX"], ["1x"]])("reports %s as not a number", (text) => {
    const onChange = vi.fn();
    render(<NumberField id="nf" aria-label="Weeks" value="" onChange={onChange} suffixes={SUFFIXES} optional />);
    fireEvent.change(box(), { target: { value: text } });
    expect(onChange).toHaveBeenCalledWith(text, { value: null, error: "Enter a number." });
  });

  it("makes letters invalid when no suffixes are given (the default)", () => {
    render(<Harness initial="5M" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
  });

  it("applies min to the value in base units", () => {
    render(<NumberField id="nf" aria-label="Weeks" value="-5B" onChange={() => {}} suffixes={SUFFIXES} min={0} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value of at least 0.");
  });
});

describe("NumberField: keyboardStep", () => {
  it("does not step and does not swallow the arrow keys when keyboardStep is false", () => {
    render(<Harness initial="30" keyboardStep={false} />);
    expect(fireEvent.keyDown(box(), { key: "ArrowUp" })).toBe(true);
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(box().value).toBe("30");
  });

  it("still blocks the letter e", () => {
    render(<Harness initial="30" keyboardStep={false} />);
    expect(fireEvent.keyDown(box(), { key: "e" })).toBe(false);
  });

  it("steps by default (unchanged)", () => {
    render(<Harness initial="30" />);
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(box().value).toBe("31");
  });
});

describe("NumberField: hideError", () => {
  it("draws no error line of its own but stays aria-invalid", () => {
    render(<NumberField id="nf" aria-label="Weeks" value="abc" onChange={() => {}} hideError />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(box()).toHaveAttribute("aria-invalid", "true");
    expect(box()).toHaveClass("border-negative");
  });

  it("passes aria-describedby through so a composite can point at its own error line", () => {
    render(
      <NumberField id="nf" aria-label="Weeks" value="abc" onChange={() => {}} hideError aria-describedby="pair-error" />,
    );
    expect(box()).toHaveAttribute("aria-describedby", "pair-error");
  });

  it("an explicit invalid prop still wins", () => {
    render(<NumberField id="nf" aria-label="Weeks" value="5" onChange={() => {}} hideError invalid />);
    expect(box()).toHaveAttribute("aria-invalid", "true");
  });
});

describe("NumberField: variant", () => {
  it("is boxed by default: 36px, radius-md, page fill, full border", () => {
    render(<Harness />);
    expect(box()).toHaveClass("h-9", "rounded-md", "border", "bg-page");
    expect(box()).not.toHaveClass("border-b", "rounded-none");
  });

  it("underline uses Input's underline variant: 32px, no radius, bottom border only", () => {
    render(<Harness variant="underline" />);
    expect(box()).toHaveClass("h-8", "rounded-none", "border-0", "border-b", "font-mono", "tabular-nums");
    expect(box()).not.toHaveClass("h-9", "rounded-md");
  });

  it("keeps the size token and the invalid style in the underline variant", () => {
    render(<Harness variant="underline" size="medium" initial="abc" />);
    expect(box()).toHaveClass("w-44", "border-negative");
  });
});
