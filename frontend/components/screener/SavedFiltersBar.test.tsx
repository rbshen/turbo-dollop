// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SavedFiltersBar } from "@/components/screener/SavedFiltersBar";
import type { SavedScreenerFilter } from "@/lib/api/types";
import { DEFAULT_FILTER_STATE } from "@/lib/screenerFilters";

// Characterization of the saved-views bar: the popover, the list, loading and
// deleting a view, the naming step and its validation, the overwrite path and
// Reset. Written against the pre-migration markup (session 10, part 3) and kept
// green through it.
//
// Everything that touches markup goes through the small selector helpers just
// below, so a markup change (role="option" rows -> real buttons, the placeholder
// -> a label) is a one-place edit and every behavioural assertion stays as it was.
const h = vi.hoisted(() => ({
  saved: [] as unknown[],
  save: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/hooks/useSavedFilters", () => ({
  useSavedFilters: () => ({ data: h.saved }),
  saveScreenerFilter: (...args: unknown[]) => h.save(...args),
  deleteScreenerFilter: (...args: unknown[]) => h.remove(...args),
}));

function view(id: number, name: string): SavedScreenerFilter {
  return {
    id,
    name,
    universe: "sp500",
    sort_field: "market_cap",
    sort_direction: "asc",
    filters: DEFAULT_FILTER_STATE,
    watchlist_id: 7,
    created_at: "",
    updated_at: "",
  } as SavedScreenerFilter;
}

const ALPHA = view(1, "Alpha");
const BRAVO = view(2, "Bravo");

// --- selector helpers: the only markup-dependent part of this file -----------
// The disclosure trigger is the one button with aria-expanded; with the list open a
// row named like the active view (/^Alpha/) matches too.
const trigger = (name: RegExp | string = /^Saved views/) =>
  screen.getAllByRole("button", { name }).find((b) => b.hasAttribute("aria-expanded"))!;
const panel = () => screen.queryByRole("group", { name: "Saved views" });
const rowButtons = () => (panel() ? within(panel()!).getAllByRole("button", { name: (n) => !n.startsWith("Delete view") && !n.startsWith("Failed to delete") }) : []);
const popoverRows = () => rowButtons();
const rowNames = () => popoverRows().map((r) => r.textContent);
const rowButton = (name: string) => within(panel()!).getByRole("button", { name });
const loadRow = (name: string) => fireEvent.click(rowButton(name));
const isActiveRow = (name: string) => rowButton(name).getAttribute("aria-current") === "true";
const deleteButton = (name: string) => screen.getByRole("button", { name: `Delete view "${name}"` });
const failedDeleteButton = (name: string) => screen.getByRole("button", { name: `Failed to delete view "${name}" — try again` });
const nameInput = () => screen.getByLabelText("View name") as HTMLInputElement;
const queryNameInput = () => screen.queryByLabelText("View name") as HTMLInputElement | null;
const saveButton = () => screen.getByRole("button", { name: /^(Save|Saving…|Saved ✓|Save failed)$/ });
// -----------------------------------------------------------------------------

const onLoad = vi.fn();
const onReset = vi.fn();

function renderBar() {
  return render(
    <SavedFiltersBar
      universe="nasdaq"
      sortField="beta"
      sortDirection="desc"
      filters={{ ...DEFAULT_FILTER_STATE, speculativeGrowth: true }}
      watchlistId={3}
      onLoad={onLoad}
      onReset={onReset}
    />
  );
}

const openList = (name?: RegExp | string) => fireEvent.click(trigger(name));
const startNaming = () => fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
const typeName = (text: string) => fireEvent.change(nameInput(), { target: { value: text } });

beforeEach(() => {
  h.saved = [];
  h.save.mockReset().mockResolvedValue(undefined);
  h.remove.mockReset().mockResolvedValue(undefined);
  onLoad.mockReset();
  onReset.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("SavedFiltersBar: the trigger and the popover", () => {
  it("reads 'Saved views' with no views, and 'Saved views (n)' with some", () => {
    const { unmount } = renderBar();
    expect(trigger()).toHaveTextContent("Saved views");
    expect(trigger()).not.toHaveTextContent("(");
    unmount();
    h.saved = [ALPHA, BRAVO];
    renderBar();
    expect(trigger()).toHaveTextContent("Saved views (2)");
  });

  it("opens and closes on clicking the trigger", () => {
    h.saved = [ALPHA];
    renderBar();
    expect(popoverRows()).toHaveLength(0);
    openList();
    expect(popoverRows()).toHaveLength(1);
    openList();
    expect(popoverRows()).toHaveLength(0);
  });

  it("says 'No saved views yet' when there are none", () => {
    renderBar();
    openList();
    expect(screen.getByText("No saved views yet")).toBeInTheDocument();
  });

  it("lists every saved view by name, in the order given", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    expect(rowNames()).toEqual(["Alpha", "Bravo"]);
  });

  it("closes on a mousedown outside and stays open on a mousedown inside", () => {
    h.saved = [ALPHA];
    renderBar();
    openList();
    fireEvent.mouseDown(rowButton("Alpha"));
    expect(popoverRows()).toHaveLength(1);
    fireEvent.mouseDown(document.body);
    expect(popoverRows()).toHaveLength(0);
  });
});

describe("SavedFiltersBar: loading a view", () => {
  it("calls onLoad with that view, closes the popover and shows the view's name on the trigger", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    loadRow("Bravo");
    expect(onLoad).toHaveBeenCalledTimes(1);
    expect(onLoad).toHaveBeenCalledWith(BRAVO);
    expect(popoverRows()).toHaveLength(0);
    expect(trigger(/^Bravo/)).toBeInTheDocument();
  });

  it("marks the loaded view as the active one when the list is reopened", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    loadRow("Bravo");
    openList(/^Bravo/);
    expect(isActiveRow("Bravo")).toBe(true);
    expect(isActiveRow("Alpha")).toBe(false);
  });
});

describe("SavedFiltersBar: deleting a view", () => {
  it("deletes by name without loading it, and leaves the popover open", async () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    await act(async () => {
      fireEvent.click(deleteButton("Bravo"));
    });
    expect(h.remove).toHaveBeenCalledTimes(1);
    expect(h.remove).toHaveBeenCalledWith("Bravo");
    expect(onLoad).not.toHaveBeenCalled();
    expect(popoverRows()).toHaveLength(2); // the mocked list is static; the popover did not close
  });

  it("deleting the active view clears the active name", async () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    loadRow("Alpha");
    expect(trigger(/^Alpha/)).toBeInTheDocument();
    openList(/^Alpha/);
    await act(async () => {
      fireEvent.click(deleteButton("Alpha"));
    });
    expect(trigger()).toHaveTextContent("Saved views (2)");
  });

  it("deleting another view leaves the active name alone", async () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    loadRow("Alpha");
    openList(/^Alpha/);
    await act(async () => {
      fireEvent.click(deleteButton("Bravo"));
    });
    expect(trigger(/^Alpha/)).toBeInTheDocument();
  });

  it("flags a failed delete on that row, then clears the flag after 3 seconds", async () => {
    vi.useFakeTimers();
    h.saved = [ALPHA, BRAVO];
    h.remove.mockRejectedValueOnce(new Error("boom"));
    renderBar();
    openList();
    await act(async () => {
      fireEvent.click(deleteButton("Alpha"));
    });
    expect(failedDeleteButton("Alpha")).toBeInTheDocument();
    expect(deleteButton("Bravo")).toBeInTheDocument(); // the other row is untouched
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(deleteButton("Alpha")).toBeInTheDocument();
  });
});

describe("SavedFiltersBar: the naming step", () => {
  it("replaces 'Save current view' and 'Reset' with the name box, and closes an open list", () => {
    h.saved = [ALPHA];
    renderBar();
    openList();
    startNaming();
    expect(popoverRows()).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Save current view" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    expect(nameInput()).toHaveFocus();
    expect(nameInput().value).toBe("");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("cannot save an empty or whitespace-only name, by button or by Enter", () => {
    renderBar();
    startNaming();
    expect(saveButton()).toBeDisabled();
    fireEvent.keyDown(nameInput(), { key: "Enter" });
    typeName("   ");
    expect(saveButton()).toBeDisabled();
    fireEvent.keyDown(nameInput(), { key: "Enter" });
    expect(h.save).not.toHaveBeenCalled();
    expect(queryNameInput()).not.toBeNull(); // still naming
  });

  it("saves the trimmed name with the current universe, sort, filters and watchlist", async () => {
    renderBar();
    startNaming();
    typeName("  My view  ");
    expect(saveButton()).toBeEnabled();
    await act(async () => {
      fireEvent.click(saveButton());
    });
    expect(h.save).toHaveBeenCalledTimes(1);
    expect(h.save).toHaveBeenCalledWith("My view", {
      universe: "nasdaq",
      sort_field: "beta",
      sort_direction: "desc",
      filters: { ...DEFAULT_FILTER_STATE, speculativeGrowth: true },
      watchlist_id: 3,
    });
  });

  it("after saving, leaves the naming step and shows the new view as the active one", async () => {
    renderBar();
    startNaming();
    typeName("My view");
    await act(async () => {
      fireEvent.click(saveButton());
    });
    expect(queryNameInput()).toBeNull();
    expect(trigger(/^My view/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save current view" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
  });

  it("Enter saves", async () => {
    renderBar();
    startNaming();
    typeName("Via enter");
    await act(async () => {
      fireEvent.keyDown(nameInput(), { key: "Enter" });
    });
    expect(h.save).toHaveBeenCalledWith("Via enter", expect.any(Object));
  });

  it("Escape cancels without saving, and the next naming step starts empty", () => {
    renderBar();
    startNaming();
    typeName("half typed");
    fireEvent.keyDown(nameInput(), { key: "Escape" });
    expect(queryNameInput()).toBeNull();
    expect(h.save).not.toHaveBeenCalled();
    startNaming();
    expect(nameInput().value).toBe("");
  });

  it("Cancel leaves the naming step without saving", () => {
    renderBar();
    startNaming();
    typeName("half typed");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(queryNameInput()).toBeNull();
    expect(h.save).not.toHaveBeenCalled();
  });

  it("shows 'Saving…' (disabled) while the save is in flight", async () => {
    let finish: () => void = () => {};
    h.save.mockReturnValueOnce(new Promise<void>((resolve) => (finish = resolve)));
    renderBar();
    startNaming();
    typeName("Slow");
    fireEvent.click(saveButton());
    expect(saveButton()).toHaveTextContent("Saving…");
    expect(saveButton()).toBeDisabled();
    await act(async () => {
      finish();
    });
  });

  it("shows 'Save failed' and stays in the naming step when the save fails, then reverts after 3 seconds", async () => {
    vi.useFakeTimers();
    h.save.mockRejectedValueOnce(new Error("boom"));
    renderBar();
    startNaming();
    typeName("Doomed");
    await act(async () => {
      fireEvent.click(saveButton());
    });
    expect(saveButton()).toHaveTextContent("Save failed");
    expect(nameInput().value).toBe("Doomed");
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(saveButton()).toHaveTextContent("Save");
    expect(saveButton()).not.toHaveTextContent("failed");
  });
});

describe("SavedFiltersBar: the overwrite path", () => {
  it("asks before overwriting an existing name and does not save yet", () => {
    h.saved = [ALPHA];
    renderBar();
    startNaming();
    typeName("Alpha");
    fireEvent.click(saveButton());
    expect(screen.getByText('A saved view named "Alpha" already exists — overwrite?')).toBeInTheDocument();
    expect(h.save).not.toHaveBeenCalled();
    expect(queryNameInput()).toBeNull();
    expect(screen.getByRole("button", { name: "Overwrite" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("compares the trimmed name, so ' Alpha ' also asks", () => {
    h.saved = [ALPHA];
    renderBar();
    startNaming();
    typeName("  Alpha ");
    fireEvent.click(saveButton());
    expect(screen.getByText('A saved view named "Alpha" already exists — overwrite?')).toBeInTheDocument();
  });

  it("Overwrite saves under that name and ends the step with the view active", async () => {
    h.saved = [ALPHA];
    renderBar();
    startNaming();
    typeName("Alpha");
    fireEvent.click(saveButton());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Overwrite" }));
    });
    expect(h.save).toHaveBeenCalledTimes(1);
    expect(h.save).toHaveBeenCalledWith("Alpha", expect.any(Object));
    expect(screen.queryByRole("button", { name: "Overwrite" })).toBeNull();
    expect(trigger(/^Alpha/)).toBeInTheDocument();
  });

  it("Enter in the name box also reaches the overwrite question, not a silent save", () => {
    h.saved = [ALPHA];
    renderBar();
    startNaming();
    typeName("Alpha");
    fireEvent.keyDown(nameInput(), { key: "Enter" });
    expect(screen.getByRole("button", { name: "Overwrite" })).toBeInTheDocument();
    expect(h.save).not.toHaveBeenCalled();
  });

  it("Cancel drops the question without saving", () => {
    h.saved = [ALPHA];
    renderBar();
    startNaming();
    typeName("Alpha");
    fireEvent.click(saveButton());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Overwrite" })).toBeNull();
    expect(h.save).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save current view" })).toBeInTheDocument();
  });
});

describe("SavedFiltersBar: Reset", () => {
  it("calls onReset", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("also forgets the active view name", () => {
    h.saved = [ALPHA];
    renderBar();
    openList();
    loadRow("Alpha");
    expect(trigger(/^Alpha/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(trigger()).toHaveTextContent("Saved views (1)");
  });
});

describe("SavedFiltersBar: layout", () => {
  it("stacks its controls full-width", () => {
    const { container } = renderBar();
    expect(container.firstElementChild).toHaveClass("flex-col", "items-stretch");
  });
});

// ---------------------------------------------------------------------------
// Session 10, part 3: the migrated bar's new behaviour.
// ---------------------------------------------------------------------------
const save = async () => {
  await act(async () => {
    fireEvent.click(saveButton());
  });
};

describe("SavedFiltersBar: disclosure semantics", () => {
  it("the trigger reports aria-expanded and controls the popover, which is a labelled group (not a listbox)", () => {
    h.saved = [ALPHA];
    renderBar();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(trigger()).not.toHaveAttribute("aria-controls");
    openList();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(panel()).toHaveAttribute("id", trigger().getAttribute("aria-controls"));
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.queryByRole("option")).toBeNull();
  });

  it("the trigger's caret is a decorative icon, not a text glyph", () => {
    renderBar();
    expect(trigger().querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(trigger().textContent).not.toContain("▾");
  });

  it("every string is sentence case", () => {
    renderBar();
    for (const name of ["Save current view", "Reset"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(trigger()).toHaveTextContent("Saved views");
  });
});

describe("SavedFiltersBar: Escape", () => {
  it("on the trigger closes the popover and keeps focus on the trigger", () => {
    h.saved = [ALPHA];
    renderBar();
    openList();
    trigger().focus();
    fireEvent.keyDown(trigger(), { key: "Escape" });
    expect(panel()).toBeNull();
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("on a row closes the popover and returns focus to the trigger", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    rowButton("Bravo").focus();
    fireEvent.keyDown(rowButton("Bravo"), { key: "Escape" });
    expect(panel()).toBeNull();
    expect(trigger()).toHaveFocus();
  });

  it("on a delete button closes the popover too, without deleting", () => {
    h.saved = [ALPHA];
    renderBar();
    openList();
    deleteButton("Alpha").focus();
    fireEvent.keyDown(deleteButton("Alpha"), { key: "Escape" });
    expect(panel()).toBeNull();
    expect(trigger()).toHaveFocus();
    expect(h.remove).not.toHaveBeenCalled();
  });

  it("does nothing while the popover is closed", () => {
    renderBar();
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    trigger().dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("still closes on an outside click", () => {
    h.saved = [ALPHA];
    renderBar();
    openList();
    fireEvent.mouseDown(document.body);
    expect(panel()).toBeNull();
  });
});

describe("SavedFiltersBar: keyboard-operable rows", () => {
  it("each view is a real load button plus a separate delete button, never one inside the other", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    for (const n of ["Alpha", "Bravo"]) {
      const load = rowButton(n);
      const del = deleteButton(n);
      expect(load.tagName).toBe("BUTTON");
      expect(del.tagName).toBe("BUTTON");
      expect(load).toHaveAttribute("type", "button");
      expect(load.contains(del)).toBe(false);
      expect(del.contains(load)).toBe(false);
      expect(load.tabIndex).toBeGreaterThanOrEqual(0);
      expect(del.tabIndex).toBeGreaterThanOrEqual(0);
    }
  });

  it("tab order is trigger, then load and delete for each row in turn", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    const order = [trigger(), rowButton("Alpha"), deleteButton("Alpha"), rowButton("Bravo"), deleteButton("Bravo")];
    for (let i = 0; i < order.length - 1; i++) {
      expect(order[i].compareDocumentPosition(order[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    const tabbable = Array.from(document.querySelectorAll<HTMLElement>("button")).filter((b) => b.tabIndex >= 0);
    expect(tabbable.slice(0, 5)).toEqual(order);
  });

  it("the delete button's accessible name includes the view name", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    expect(deleteButton("Alpha")).toHaveAccessibleName('Delete view "Alpha"');
    expect(deleteButton("Bravo")).toHaveAccessibleName('Delete view "Bravo"');
    expect(deleteButton("Alpha").querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("names a failed delete as a failure, with the view name", async () => {
    vi.useFakeTimers();
    h.saved = [ALPHA];
    h.remove.mockRejectedValueOnce(new Error("boom"));
    renderBar();
    openList();
    await act(async () => {
      fireEvent.click(deleteButton("Alpha"));
    });
    expect(failedDeleteButton("Alpha")).toHaveAccessibleName('Failed to delete view "Alpha" — try again');
    expect(failedDeleteButton("Alpha")).toHaveClass("text-negative");
  });

  it("loading returns focus to the trigger", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    rowButton("Bravo").focus();
    loadRow("Bravo");
    expect(trigger(/^Bravo/)).toHaveFocus();
  });

  it("deleting a row moves focus to the next row", async () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    deleteButton("Alpha").focus();
    await act(async () => {
      fireEvent.click(deleteButton("Alpha"));
    });
    expect(rowButton("Bravo")).toHaveFocus();
  });

  it("deleting the last row moves focus to the previous row", async () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    await act(async () => {
      fireEvent.click(deleteButton("Bravo"));
    });
    expect(rowButton("Alpha")).toHaveFocus();
  });

  it("deleting the only row moves focus to the trigger", async () => {
    h.saved = [ALPHA];
    renderBar();
    openList();
    await act(async () => {
      fireEvent.click(deleteButton("Alpha"));
    });
    expect(trigger()).toHaveFocus();
  });

  it("ignores a second click on a delete that is already in flight, and keeps it focusable", async () => {
    let finish: () => void = () => {};
    h.remove.mockReturnValueOnce(new Promise<void>((resolve) => (finish = resolve)));
    h.saved = [ALPHA];
    renderBar();
    openList();
    deleteButton("Alpha").focus();
    fireEvent.click(deleteButton("Alpha"));
    fireEvent.click(deleteButton("Alpha"));
    expect(h.remove).toHaveBeenCalledTimes(1);
    expect(deleteButton("Alpha")).toHaveAttribute("aria-disabled", "true");
    expect(deleteButton("Alpha")).toHaveFocus();
    await act(async () => {
      finish();
    });
  });
});

describe("SavedFiltersBar: the active-view marker", () => {
  it("is neutral (no brand colour) and exposed with aria-current, not colour alone", () => {
    h.saved = [ALPHA, BRAVO];
    renderBar();
    openList();
    loadRow("Alpha");
    openList(/^Alpha/);
    const active = rowButton("Alpha");
    expect(active).toHaveAttribute("aria-current", "true");
    expect(rowButton("Bravo")).not.toHaveAttribute("aria-current");
    const check = active.querySelector("svg");
    expect(check).not.toBeNull();
    expect(check).toHaveAttribute("aria-hidden", "true");
    expect(check).toHaveClass("text-text-primary");
    expect(panel()!.innerHTML).not.toContain("text-brand");
    expect(active).toHaveClass("font-medium", "text-text-primary");
    expect(active.parentElement).toHaveClass("bg-surface-2");
    expect(rowButton("Bravo").querySelector("svg")).toBeNull();
  });
});

describe("SavedFiltersBar: the naming step's layout", () => {
  it("has a visible 'View name' label tied to a boxed, full-width Input on its own row", () => {
    renderBar();
    startNaming();
    const label = screen.getByText("View name", { selector: "label" });
    expect(label).toHaveAttribute("for", nameInput().id);
    expect(nameInput()).toHaveAttribute("type", "text");
    expect(nameInput()).toHaveClass("w-full", "h-9", "rounded-md", "border", "border-border-control");
    expect(nameInput().className).not.toContain("focus:outline-none");
    expect(nameInput()).not.toHaveAttribute("maxlength");
  });

  it("puts Save and Cancel together on a row of their own, below the Input", () => {
    renderBar();
    startNaming();
    const save = saveButton();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(save.parentElement).toBe(cancel.parentElement);
    expect(save.parentElement).toHaveClass("flex");
    expect(save.parentElement).not.toContainElement(nameInput());
    expect(nameInput().compareDocumentPosition(save) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // the step is a single column, so nothing can run past the sidebar's width
    expect(save.parentElement!.parentElement).toHaveClass("flex-col");
    expect(save.parentElement!.parentElement).not.toHaveClass("flex-row");
  });

  it("uses outline Buttons for Save and Cancel", () => {
    renderBar();
    startNaming();
    for (const b of [saveButton(), screen.getByRole("button", { name: "Cancel" })]) {
      expect(b).toHaveClass("border", "border-border-input", "hover:border-brand", "bg-transparent");
    }
  });

  it("sets no maximum length, however long the name", async () => {
    renderBar();
    startNaming();
    const long = "x".repeat(300);
    typeName(long);
    expect(nameInput().value).toBe(long);
    await save();
    expect(h.save).toHaveBeenCalledWith(long, expect.any(Object));
  });

  it("has no horizontal layout any more: the bar is always one column", () => {
    const { container } = renderBar();
    expect(container.firstElementChild).toHaveClass("flex-col");
    expect(container.firstElementChild).not.toHaveClass("flex-row");
  });
});

describe("SavedFiltersBar: the overwrite row's layout", () => {
  function openOverwrite(name = "Alpha") {
    h.saved = [view(1, name)];
    renderBar();
    startNaming();
    typeName(name);
    fireEvent.click(saveButton());
  }

  it("puts the message on its own line with the two buttons on a row below it", () => {
    openOverwrite();
    const message = screen.getByText('A saved view named "Alpha" already exists — overwrite?');
    const overwrite = screen.getByRole("button", { name: "Overwrite" });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(message.tagName).toBe("P");
    expect(overwrite.parentElement).toBe(cancel.parentElement);
    expect(overwrite.parentElement).not.toContainElement(message);
    expect(overwrite.parentElement!.parentElement).toBe(message.parentElement);
    expect(message.parentElement).toHaveClass("flex-col");
    expect(message.compareDocumentPosition(overwrite) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("wraps a long unbroken name instead of overflowing", () => {
    openOverwrite("a".repeat(120));
    expect(screen.getByText(/already exists/)).toHaveClass("break-words");
  });

  it("keeps the warning colour on the message and the Overwrite button, both outline Buttons", () => {
    openOverwrite();
    expect(screen.getByText(/already exists/)).toHaveClass("text-warn");
    const overwrite = screen.getByRole("button", { name: "Overwrite" });
    expect(overwrite).toHaveClass("text-warn", "border", "hover:border-warn");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("border", "border-border-input", "bg-transparent");
  });
});

describe("SavedFiltersBar: names containing '/'", () => {
  it("shows an inline error, marks the box invalid and leaves the typed text exactly as typed", () => {
    renderBar();
    startNaming();
    typeName("growth/value");
    expect(nameInput().value).toBe("growth/value");
    expect(screen.getByRole("alert")).toHaveTextContent('A view name cannot contain "/".');
    expect(nameInput()).toHaveAttribute("aria-invalid", "true");
    expect(nameInput().getAttribute("aria-describedby")).toBe(screen.getByRole("alert").id);
    expect(nameInput()).toHaveClass("border-negative");
  });

  it("cannot be saved, by button or by Enter", async () => {
    renderBar();
    startNaming();
    typeName("a/b");
    expect(saveButton()).toBeDisabled();
    await act(async () => {
      fireEvent.keyDown(nameInput(), { key: "Enter" });
    });
    expect(h.save).not.toHaveBeenCalled();
    expect(queryNameInput()).not.toBeNull(); // still naming
  });

  it("is judged on the text as typed: a slash among spaces is still rejected", () => {
    renderBar();
    startNaming();
    typeName("  a / b  ");
    expect(saveButton()).toBeDisabled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("clears the error and re-enables Save as soon as the slash is removed", async () => {
    renderBar();
    startNaming();
    typeName("a/b");
    typeName("a b");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(nameInput()).not.toHaveAttribute("aria-invalid");
    expect(saveButton()).toBeEnabled();
    await save();
    expect(h.save).toHaveBeenCalledWith("a b", expect.any(Object));
  });

  it("shows no error for an empty box, and Cancel and Escape still work with a slash typed", () => {
    renderBar();
    startNaming();
    expect(screen.queryByRole("alert")).toBeNull();
    typeName("a/b");
    fireEvent.keyDown(nameInput(), { key: "Escape" });
    expect(queryNameInput()).toBeNull();
    startNaming();
    expect(screen.queryByRole("alert")).toBeNull();
    typeName("a/b");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(queryNameInput()).toBeNull();
  });

  it.each(["a b", "a?b", "a#b", "100%", "a+b", "a&b=c", "a;b", "é ü", "a\\b"])(
    "saves %j unchanged (the other URL-reserved characters are not blocked)",
    async (name) => {
      renderBar();
      startNaming();
      typeName(name);
      expect(screen.queryByRole("alert")).toBeNull();
      await save();
      expect(h.save).toHaveBeenCalledWith(name, expect.any(Object));
    }
  );
});

// Session 16: the trigger is an outline Button at sm (32px, like the Save and Reset buttons beside it) with the CaretDown
// icon, not a hand-written ghost-plus-border button. Its border stays neutral on hover.
describe("SavedFiltersBar: the trigger is a Button", () => {
  it("is an outline Button at size sm: 32px, the input border, the same text size as its neighbours", () => {
    renderBar();
    const t = trigger();
    expect(t).toHaveClass("h-8", "text-xs", "border", "border-border-input", "bg-transparent", "px-3");
    expect(t.className).not.toMatch(/bg-surface(?!-)/);
    expect(t).toHaveAttribute("type", "button");
    expect(screen.getByRole("button", { name: "Save current view" })).toHaveClass("h-8", "text-xs", "border-border-input");
  });

  it("does not turn its border brand on hover (a neutral disclosure, not an action)", () => {
    renderBar();
    expect(trigger()).toHaveClass("hover:border-border-input");
    expect(trigger().className).not.toMatch(/hover:border-brand/);
  });

  it("keeps a decorative 12px caret at the end of the label, and a truncating label", () => {
    renderBar();
    const icon = trigger().querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon).toHaveClass("shrink-0", "text-text-tertiary");
    expect(trigger().firstElementChild).toHaveClass("truncate");
    expect(trigger()).toHaveClass("gap-1.5");
  });
});
