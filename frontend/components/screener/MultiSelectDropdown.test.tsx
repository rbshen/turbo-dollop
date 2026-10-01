// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";

afterEach(cleanup);

// Characterization of MultiSelectDropdown's keyboard, focus and ARIA behaviour.
// It was written against the version with hand-styled native checkboxes and must
// keep passing unchanged after the options move onto the bare neutral Checkbox.
const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
  { value: "c", label: "Charlie" },
];

function Harness({ initial = [] as string[], onChange }: { initial?: string[]; onChange?: (v: string[]) => void }) {
  const [selected, setSelected] = useState(initial);
  return (
    <div>
      <button>before</button>
      <MultiSelectDropdown
        label="Letters"
        options={OPTIONS}
        selected={selected}
        onChange={(v) => {
          setSelected(v);
          onChange?.(v);
        }}
      />
      <button>after</button>
    </div>
  );
}

const trigger = () => screen.getByRole("button", { name: /Letters|Alpha|Bravo|Charlie/ });
const listbox = () => screen.getByRole("listbox", { name: "Letters" });
const boxes = () => within(listbox()).getAllByRole("checkbox") as HTMLInputElement[];
const open = () => fireEvent.click(trigger());
const key = (el: Element, k: string, init: KeyboardEventInit = {}) => fireEvent.keyDown(el, { key: k, ...init });

describe("MultiSelectDropdown: opening and focus", () => {
  it("starts closed, with the trigger named by its label and the popup ARIA on the trigger", () => {
    render(<Harness />);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger()).toHaveAccessibleName("Letters: none selected");
    expect(trigger()).toHaveAttribute("aria-haspopup", "listbox");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("opens on click, moves focus to the first option, and exposes the listbox ARIA", () => {
    render(<Harness />);
    open();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(listbox()).toHaveAttribute("aria-multiselectable", "true");
    expect(boxes()).toHaveLength(3);
    expect(boxes()[0]).toHaveFocus();
    const options = within(listbox()).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Alpha", "Bravo", "Charlie"]);
    expect(options.every((o) => o.getAttribute("aria-selected") === "false")).toBe(true);
  });

  it("lands on Clear when something is already selected", () => {
    render(<Harness initial={["b"]} />);
    open();
    expect(screen.getByRole("button", { name: "Clear" })).toHaveFocus();
  });

  it("reflects the selection in the options and in the trigger text", () => {
    render(<Harness initial={["b", "c"]} />);
    expect(trigger()).toHaveAccessibleName("Letters (2): 2 selected");
    expect(trigger()).toHaveTextContent("Letters (2)"); // the visible text is unchanged
    open();
    expect(boxes().map((b) => b.checked)).toEqual([false, true, true]);
    expect(within(listbox()).getAllByRole("option").map((o) => o.getAttribute("aria-selected"))).toEqual(["false", "true", "true"]);
  });
});

describe("MultiSelectDropdown: the trigger's accessible name and caret", () => {
  it.each([
    [[] as string[], "Letters: none selected", "Letters"],
    [["b"], "Letters: Bravo", "Bravo"],
    [["a", "c"], "Letters (2): 2 selected", "Letters (2)"],
    [["a", "b", "c"], "Letters (3): 3 selected", "Letters (3)"],
  ])("with %j selected it is named %s and still reads %s", (initial, name, visible) => {
    render(<Harness initial={initial} />);
    expect(trigger()).toHaveAccessibleName(name);
    expect(trigger()).toHaveTextContent(new RegExp(`^${visible.replace(/[()]/g, "\\$&")}$`));
  });

  it.each([[[] as string[]], [["b"]], [["a", "c"]], [["a", "b", "c"]]])(
    "with %j selected the visible text is contained in the accessible name (label in name)",
    (initial) => {
      render(<Harness initial={initial} />);
      const visible = (trigger().textContent ?? "").trim();
      expect(visible).not.toBe("");
      expect(trigger().getAttribute("aria-label")).toContain(visible);
    },
  );

  it("follows the selection as options are toggled", () => {
    render(<Harness />);
    open();
    fireEvent.click(boxes()[0]);
    expect(trigger()).toHaveAccessibleName("Letters: Alpha");
    fireEvent.click(boxes()[2]);
    expect(trigger()).toHaveAccessibleName("Letters (2): 2 selected");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(trigger()).toHaveAccessibleName("Letters: none selected");
  });

  it("uses the option's label, not its stored value, when one is selected", () => {
    render(<Harness initial={["c"]} />);
    expect(trigger()).toHaveAccessibleName("Letters: Charlie");
  });

  it("has a decorative CaretDown icon and no text glyph", () => {
    render(<Harness />);
    const icon = trigger().querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(trigger().textContent).not.toContain("▾");
  });

  it("keeps aria-haspopup and tracks aria-expanded through open, Escape and a second click", () => {
    render(<Harness />);
    expect(trigger()).toHaveAttribute("aria-haspopup", "listbox");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    open();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    key(listbox(), "Escape");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    open();
    open();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("leaves the listbox named by the bare label", () => {
    render(<Harness initial={["a"]} />);
    open();
    expect(listbox()).toHaveAccessibleName("Letters");
  });
});

describe("MultiSelectDropdown: toggling", () => {
  it("toggles an option on click and reports the new array", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    open();
    fireEvent.click(boxes()[1]);
    expect(onChange).toHaveBeenLastCalledWith(["b"]);
    expect(boxes()[1].checked).toBe(true);
    fireEvent.click(boxes()[0]);
    expect(onChange).toHaveBeenLastCalledWith(["b", "a"]);
    fireEvent.click(boxes()[1]);
    expect(onChange).toHaveBeenLastCalledWith(["a"]);
  });

  it("toggles when the option's label text is clicked", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    open();
    fireEvent.click(within(listbox()).getByText("Charlie"));
    expect(onChange).toHaveBeenLastCalledWith(["c"]);
  });

  it("Clear empties the selection", () => {
    const onChange = vi.fn();
    render(<Harness initial={["a", "b"]} onChange={onChange} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("shows 'No options' for an empty list", () => {
    render(<MultiSelectDropdown label="Letters" options={[]} selected={[]} onChange={() => {}} />);
    open();
    expect(screen.getByText("No options")).toBeInTheDocument();
  });
});

describe("MultiSelectDropdown: roving keyboard focus", () => {
  it("ArrowDown and ArrowUp move between options and wrap around", () => {
    render(<Harness />);
    open();
    key(boxes()[0], "ArrowDown");
    expect(boxes()[1]).toHaveFocus();
    key(boxes()[1], "ArrowDown");
    expect(boxes()[2]).toHaveFocus();
    key(boxes()[2], "ArrowDown");
    expect(boxes()[0]).toHaveFocus(); // wraps forward
    key(boxes()[0], "ArrowUp");
    expect(boxes()[2]).toHaveFocus(); // wraps backward
    key(boxes()[2], "ArrowUp");
    expect(boxes()[1]).toHaveFocus();
  });

  it("Home and End jump to the first and last option", () => {
    render(<Harness />);
    open();
    key(boxes()[0], "End");
    expect(boxes()[2]).toHaveFocus();
    key(boxes()[2], "Home");
    expect(boxes()[0]).toHaveFocus();
  });

  it("the arrow keys do nothing from the Clear button (only options rove)", () => {
    render(<Harness initial={["a"]} />);
    open();
    const clear = screen.getByRole("button", { name: "Clear" });
    expect(clear).toHaveFocus();
    key(clear, "ArrowDown");
    expect(clear).toHaveFocus();
  });

  it("prevents the default of the roving keys so the page does not scroll", () => {
    render(<Harness />);
    open();
    for (const k of ["ArrowDown", "ArrowUp", "Home", "End"]) {
      const notPrevented = fireEvent.keyDown(boxes()[0], { key: k });
      expect(notPrevented).toBe(false);
    }
  });
});

describe("MultiSelectDropdown: focus trap", () => {
  it("Tab on the last option wraps to the first (no Clear when nothing is selected)", () => {
    render(<Harness />);
    open();
    boxes()[2].focus();
    const notPrevented = key(boxes()[2], "Tab");
    expect(notPrevented).toBe(false);
    expect(boxes()[0]).toHaveFocus();
  });

  it("Shift+Tab on the first option wraps to the last", () => {
    render(<Harness />);
    open();
    key(boxes()[0], "Tab", { shiftKey: true });
    expect(boxes()[2]).toHaveFocus();
  });

  it("with Clear present, Clear is the first stop of the loop", () => {
    render(<Harness initial={["a"]} />);
    open();
    const clear = screen.getByRole("button", { name: "Clear" });
    boxes()[2].focus();
    key(boxes()[2], "Tab");
    expect(clear).toHaveFocus();
    key(clear, "Tab", { shiftKey: true });
    expect(boxes()[2]).toHaveFocus();
  });

  it("Tab in the middle of the list is left to the browser (not prevented)", () => {
    render(<Harness />);
    open();
    boxes()[1].focus();
    expect(key(boxes()[1], "Tab")).toBe(true);
  });
});

describe("MultiSelectDropdown: closing", () => {
  it("Escape inside the panel closes it and returns focus to the trigger", () => {
    render(<Harness />);
    open();
    key(boxes()[1], "Escape");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("Escape on the trigger while open closes it too", () => {
    render(<Harness />);
    open();
    key(trigger(), "Escape");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger()).toHaveFocus();
  });

  it("Escape while closed does nothing", () => {
    render(<Harness />);
    expect(key(trigger(), "Escape")).toBe(true);
  });

  it("a mousedown outside closes it, and a mousedown inside does not", () => {
    render(<Harness />);
    open();
    fireEvent.mouseDown(boxes()[0]);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("button", { name: "after" }));
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("clicking the trigger again closes it", () => {
    render(<Harness />);
    open();
    open();
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});

// Session 16: the trigger is the kit's boxed field (the same 36px box, border, radius and caret as Select) at the
// sidebar column's full width, and its border never turns brand on hover. The behaviour above is untouched.
describe("MultiSelectDropdown: the trigger is a boxed field", () => {
  it("is the kit's 36px box: h-9, radius-md, a 1px border-control, the page fill, at full width", () => {
    render(<Harness />);
    const t = trigger();
    expect(t).toHaveClass("h-9", "rounded-md", "border", "border-border-control", "bg-page", "w-full", "text-sm");
    expect(t.className).not.toMatch(/h-8|border-border-input|bg-surface/);
  });

  it("has no brand border or fill, in any state, and does not hand-write the ghost-plus-border look", () => {
    render(<Harness />);
    expect(trigger().className).not.toMatch(/brand/);
    cleanup();
    render(<Harness initial={["a", "b"]} />);
    expect(trigger().className).not.toMatch(/brand/);
  });

  it("puts the label on the left and a decorative caret on the right, the same 12px bold caret as Select", () => {
    render(<Harness />);
    const t = trigger();
    expect(t).toHaveClass("flex", "justify-between");
    expect(t.firstElementChild).toHaveTextContent("Letters");
    expect(t.firstElementChild).toHaveClass("truncate");
    const icon = t.querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon).toHaveClass("shrink-0", "text-text-tertiary");
  });

  it("is secondary text when nothing is chosen, and the filter-active tone once something is", () => {
    render(<Harness />);
    expect(trigger()).toHaveClass("text-text-secondary");
    expect(trigger()).not.toHaveClass("text-filter-active");
    cleanup();
    render(<Harness initial={["a"]} />);
    expect(trigger()).toHaveClass("text-filter-active");
    expect(trigger()).not.toHaveClass("text-text-secondary");
    expect(trigger()).not.toHaveClass("text-text-primary");
  });
});
