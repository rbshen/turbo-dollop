// @vitest-environment jsdom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RangeField, REVERSED_RANGE_MESSAGE, type RangeFieldProps, type RangeValue } from "@/components/ui/range-field";
import { formatMarketCapInput, EMPTY_RANGE, MARKET_CAP_SUFFIXES } from "@/lib/screenerFilters";

afterEach(cleanup);

// The parent holds the exact object onChange emitted, as a real page does.
function Harness({
  initial = { min: null, max: null },
  onValue,
  ...props
}: { initial?: RangeValue; onValue?: (v: RangeValue) => void } & Partial<Omit<RangeFieldProps, "value" | "onChange">>) {
  const [value, setValue] = useState<RangeValue>(initial);
  return (
    <div>
      <RangeField
        label="Growth"
        value={value}
        onChange={(v) => {
          setValue(v);
          onValue?.(v);
        }}
        {...props}
      />
      <button type="button" onClick={() => setValue(EMPTY_RANGE)}>
        reset
      </button>
      <button type="button" onClick={() => setValue({ min: 70, max: 90 })}>
        load
      </button>
      <output data-testid="value">{JSON.stringify(value)}</output>
    </div>
  );
}

const minBox = () => screen.getByRole("textbox", { name: "Minimum" }) as HTMLInputElement;
const maxBox = () => screen.getByRole("textbox", { name: "Maximum" }) as HTMLInputElement;
const type = (box: HTMLInputElement, text: string) => {
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value: text } });
};
const committed = () => JSON.parse(screen.getByTestId("value").textContent ?? "null") as RangeValue;

describe("RangeField: structure and accessible names", () => {
  it("is a group named by its label, with Minimum and Maximum boxes and Min/Max placeholders", () => {
    render(<Harness />);
    const group = screen.getByRole("group", { name: "Growth" });
    expect(group).toContainElement(minBox());
    expect(group).toContainElement(maxBox());
    expect(minBox()).toHaveAttribute("placeholder", "Min");
    expect(maxBox()).toHaveAttribute("placeholder", "Max");
    expect(screen.getByText("Growth").tagName).toBe("LABEL");
  });

  it("puts the unit in the label row and uses two short (96px) boxes by default", () => {
    render(<Harness unit="%" />);
    const unit = screen.getByText("%");
    expect(unit.parentElement).toBe(screen.getByText("Growth").parentElement);
    expect(minBox()).toHaveClass("w-24", "h-9");
    expect(maxBox()).toHaveClass("w-24", "h-9");
  });

  it("passes the underline variant to both boxes", () => {
    render(<Harness variant="underline" />);
    for (const box of [minBox(), maxBox()]) expect(box).toHaveClass("h-8", "border-b", "rounded-none");
  });

  it("turns the label orange only while a side holds a value", () => {
    const { unmount } = render(<Harness />);
    expect(screen.getByText("Growth")).not.toHaveClass("text-filter-active");
    unmount();
    render(<Harness initial={{ min: 5, max: null }} />);
    expect(screen.getByText("Growth")).toHaveClass("text-filter-active");
  });

  it("does not step with the arrow keys", () => {
    render(<Harness initial={{ min: 5, max: null }} />);
    fireEvent.keyDown(minBox(), { key: "ArrowUp" });
    expect(minBox().value).toBe("5");
    expect(committed()).toEqual({ min: 5, max: null });
  });

  it("shows an optional one-line hint under the pair", () => {
    render(<Harness hint="e.g. 500M, 2B, 1T" />);
    expect(screen.getByText("e.g. 500M, 2B, 1T")).toBeInTheDocument();
  });
});

describe("RangeField: valid text commits at once", () => {
  it("commits each side as it is typed", () => {
    const onValue = vi.fn();
    render(<Harness onValue={onValue} />);
    type(minBox(), "12");
    expect(onValue).toHaveBeenLastCalledWith({ min: 12, max: null });
    type(maxBox(), "40.5");
    expect(onValue).toHaveBeenLastCalledWith({ min: 12, max: 40.5 });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("commits '12.' and '.5' immediately and leaves the typed text alone", () => {
    render(<Harness />);
    type(minBox(), ".5");
    expect(committed()).toEqual({ min: 0.5, max: null });
    expect(minBox().value).toBe(".5");
    type(maxBox(), "12.");
    expect(committed()).toEqual({ min: 0.5, max: 12 });
    expect(maxBox().value).toBe("12.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("commits a negative number and emptying the box commits null", () => {
    render(<Harness initial={{ min: 5, max: null }} />);
    type(minBox(), "-3");
    expect(committed()).toEqual({ min: -3, max: null });
    type(minBox(), "");
    expect(committed()).toEqual({ min: null, max: null });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("parses market-cap suffixes M, B and T when given suffixes", () => {
    render(<Harness label="Mkt cap" suffixes={MARKET_CAP_SUFFIXES} min={0} />);
    type(minBox(), "500M");
    expect(committed().min).toBe(500_000_000);
    type(minBox(), "2 b");
    expect(committed().min).toBe(2_000_000_000);
    type(maxBox(), "5T");
    expect(committed().max).toBe(5_000_000_000_000);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("RangeField: incomplete prefixes", () => {
  it.each([["-"], ["."], ["-."]])("holds the previous value and shows no error for %s while focused", (text) => {
    const onValue = vi.fn();
    render(<Harness initial={{ min: 5, max: null }} onValue={onValue} />);
    type(minBox(), text);
    expect(onValue).not.toHaveBeenCalled();
    expect(committed()).toEqual({ min: 5, max: null });
    expect(minBox().value).toBe(text);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(minBox()).not.toHaveAttribute("aria-invalid");
  });

  it("becomes invalid on blur: the side goes inactive (null) and the error shows", () => {
    render(<Harness initial={{ min: 5, max: null }} />);
    type(minBox(), "-");
    fireEvent.blur(minBox());
    expect(committed()).toEqual({ min: null, max: null });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(minBox()).toHaveAttribute("aria-invalid", "true");
    expect(maxBox()).not.toHaveAttribute("aria-invalid");
  });

  it("clears the blur error once the text is completed", () => {
    render(<Harness />);
    type(minBox(), ".");
    fireEvent.blur(minBox());
    expect(screen.getByRole("alert")).toBeInTheDocument();
    type(minBox(), ".5");
    expect(committed()).toEqual({ min: 0.5, max: null });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not emit on a plain blur of valid text", () => {
    const onValue = vi.fn();
    render(<Harness initial={{ min: 5, max: null }} onValue={onValue} />);
    fireEvent.focus(minBox());
    fireEvent.blur(minBox());
    expect(onValue).not.toHaveBeenCalled();
  });
});

describe("RangeField: invalid text", () => {
  it.each([["1x"], ["abc"], ["5e"]])("makes that side inactive at once and shows an error for %s", (text) => {
    render(<Harness initial={{ min: 5, max: 9 }} />);
    type(minBox(), text);
    expect(committed()).toEqual({ min: null, max: 9 });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(minBox()).toHaveAttribute("aria-invalid", "true");
    expect(maxBox()).not.toHaveAttribute("aria-invalid");
    expect(minBox().value).toBe(text);
  });

  it("rejects a value below min without correcting it", () => {
    render(<Harness label="Mkt cap" suffixes={MARKET_CAP_SUFFIXES} min={0} initial={{ min: 1e9, max: null }} />);
    type(minBox(), "-5B");
    expect(committed()).toEqual({ min: null, max: null });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a value of at least 0.");
    expect(minBox().value).toBe("-5B");
  });

  it("rejects suffix letters when no suffixes are given", () => {
    render(<Harness />);
    type(minBox(), "5M");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(committed()).toEqual({ min: null, max: null });
  });

  it("links the one error line to the boxes with aria-describedby", () => {
    render(<Harness />);
    type(minBox(), "1x");
    const alert = screen.getByRole("alert");
    expect(minBox().getAttribute("aria-describedby")).toContain(alert.id);
  });
});

describe("RangeField: never clamps, swaps or corrects", () => {
  it("keeps a reversed pair exactly as typed", () => {
    render(<Harness />);
    type(minBox(), "90");
    type(maxBox(), "10");
    expect(committed()).toEqual({ min: 90, max: 10 });
    expect(minBox().value).toBe("90");
    expect(maxBox().value).toBe("10");
  });

  it("does not round, reformat or snap the typed text", () => {
    render(<Harness />);
    type(minBox(), "007.50");
    expect(minBox().value).toBe("007.50");
    expect(committed().min).toBe(7.5);
    fireEvent.blur(minBox());
    expect(minBox().value).toBe("007.50");
  });
});

describe("RangeField: reversed range", () => {
  it("shows one pair-level message and marks the Max box alone invalid", () => {
    render(<Harness />);
    type(minBox(), "90");
    type(maxBox(), "10");
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent(REVERSED_RANGE_MESSAGE);
    expect(REVERSED_RANGE_MESSAGE).toBe("Min is higher than max, so no ticker can match.");
    expect(maxBox()).toHaveAttribute("aria-invalid", "true");
    expect(minBox()).not.toHaveAttribute("aria-invalid");
  });

  it("goes away when the range is no longer reversed, and equal min and max is fine", () => {
    render(<Harness initial={{ min: 90, max: 10 }} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    type(maxBox(), "90");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(maxBox()).not.toHaveAttribute("aria-invalid");
  });

  it("shows exactly one error line even when both boxes hold invalid text", () => {
    render(<Harness />);
    type(minBox(), "1x");
    type(maxBox(), "2y");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(minBox()).toHaveAttribute("aria-invalid", "true");
    expect(maxBox()).toHaveAttribute("aria-invalid", "true");
  });

  it("lets a text error win over the reversed message", () => {
    render(<Harness initial={{ min: 90, max: 10 }} />);
    type(minBox(), "1x");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number.");
    expect(maxBox()).not.toHaveAttribute("aria-invalid");
  });
});

describe("RangeField: external changes re-sync the boxes", () => {
  it("shows the shortest exact market-cap form on mount", () => {
    render(<Harness label="Mkt cap" suffixes={MARKET_CAP_SUFFIXES} initial={{ min: 1e9, max: 2.5e12 }} />);
    expect(minBox().value).toBe("1B");
    expect(maxBox().value).toBe("2.5T");
    expect(formatMarketCapInput(1e9)).toBe("1B");
  });

  it("shows plain numbers without suffixes", () => {
    render(<Harness initial={{ min: 70, max: 12.5 }} />);
    expect(minBox().value).toBe("70");
    expect(maxBox().value).toBe("12.5");
  });

  it("updates the boxes on an external change (Load), and clears them on Reset", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("load"));
    expect(minBox().value).toBe("70");
    expect(maxBox().value).toBe("90");
    fireEvent.click(screen.getByText("reset"));
    expect(minBox().value).toBe("");
    expect(maxBox().value).toBe("");
  });

  it("(b) re-syncs to an externally provided new object even when it equals the current values and a draft holds invalid text", () => {
    render(<Harness />);
    type(minBox(), "1x");
    expect(committed()).toEqual({ min: null, max: null });
    expect(screen.getByRole("alert")).toBeInTheDocument();
    // EMPTY_RANGE is a different object from the one the field emitted, though the numbers are equal.
    fireEvent.click(screen.getByText("reset"));
    expect(minBox().value).toBe("");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(minBox()).not.toHaveAttribute("aria-invalid");
  });

  it("(b) re-syncs an equal-valued new object passed on a plain re-render", () => {
    const onChange = vi.fn();
    const { rerender } = render(<RangeField label="Growth" value={{ min: null, max: null }} onChange={onChange} />);
    type(minBox(), "1x");
    rerender(<RangeField label="Growth" value={{ min: null, max: null }} onChange={onChange} />);
    expect(minBox().value).toBe("");
  });

  it("re-syncs on Reset to the very object the field mounted with, after a Load", () => {
    const mounted = { min: null, max: null };
    const onChange = vi.fn();
    const { rerender } = render(<RangeField label="Growth" value={mounted} onChange={onChange} />);
    rerender(<RangeField label="Growth" value={{ min: 70, max: 90 }} onChange={onChange} />);
    expect(minBox().value).toBe("70");
    rerender(<RangeField label="Growth" value={mounted} onChange={onChange} />);
    expect(minBox().value).toBe("");
    expect(maxBox().value).toBe("");
  });

  it("(a) never overwrites typing when re-rendered with the same object", () => {
    const initial = { min: null, max: null };
    const onChange = vi.fn();
    const { rerender } = render(<RangeField label="Growth" value={initial} onChange={onChange} />);
    type(minBox(), "12.");
    // The parent ignored onChange and re-renders with the SAME object it already had.
    rerender(<RangeField label="Growth" value={initial} onChange={onChange} />);
    rerender(<RangeField label="Growth" value={initial} onChange={onChange} />);
    expect(minBox().value).toBe("12.");
    expect(onChange).toHaveBeenCalledWith({ min: 12, max: null });
  });

  it("(a) never overwrites typing when the parent hands back the emitted object", () => {
    const emitted: RangeValue[] = [];
    const { rerender } = render(<RangeField label="Growth" value={EMPTY_RANGE} onChange={(v) => emitted.push(v)} />);
    type(minBox(), "12.");
    rerender(<RangeField label="Growth" value={emitted[0]} onChange={(v) => emitted.push(v)} />);
    expect(minBox().value).toBe("12.");
    type(maxBox(), ".5");
    rerender(<RangeField label="Growth" value={emitted[1]} onChange={(v) => emitted.push(v)} />);
    expect(minBox().value).toBe("12.");
    expect(maxBox().value).toBe(".5");
  });

  it("does not touch the other box when one side is typed in", () => {
    render(<Harness initial={{ min: null, max: 2e9 }} label="Mkt cap" suffixes={MARKET_CAP_SUFFIXES} />);
    type(minBox(), "1.");
    expect(maxBox().value).toBe("2B");
  });

  it("starts fresh on a remount", () => {
    const { unmount } = render(<Harness />);
    type(minBox(), "1x");
    unmount();
    render(<Harness initial={{ min: 1e9, max: null }} label="Mkt cap" suffixes={MARKET_CAP_SUFFIXES} />);
    expect(minBox().value).toBe("1B");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("RangeField: one error line", () => {
  it("renders at most one alert in every state it can reach", () => {
    render(<Harness />);
    for (const [box, text] of [
      [minBox, "x"],
      [maxBox, "y"],
      [minBox, "50"],
      [maxBox, "10"],
    ] as const) {
      act(() => {
        type(box(), text);
      });
      expect(screen.queryAllByRole("alert").length).toBeLessThanOrEqual(1);
    }
  });
});
