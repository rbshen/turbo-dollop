// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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
const trigger = (name: RegExp | string = /^Saved views/) => screen.getByRole("button", { name });
const popoverRows = () => screen.queryAllByRole("option");
const rowNames = () => popoverRows().map((r) => r.textContent);
const loadRow = (name: string) => fireEvent.click(screen.getByRole("option", { name }));
const isActiveRow = (name: string) => screen.getByRole("option", { name }).getAttribute("aria-selected") === "true";
const deleteButton = (name: string) => screen.getByTitle(`Delete "${name}"`);
const failedDeleteButton = (name: string) => screen.getByTitle(`Failed to delete "${name}" — try again`);
const nameInput = () => screen.getByPlaceholderText("View name") as HTMLInputElement;
const queryNameInput = () => screen.queryByPlaceholderText("View name") as HTMLInputElement | null;
const saveButton = () => screen.getByRole("button", { name: /^(Save|Saving…|Saved ✓|Save failed)$/ });
// -----------------------------------------------------------------------------

const onLoad = vi.fn();
const onReset = vi.fn();

function renderBar() {
  return render(
    <SavedFiltersBar
      layout="vertical"
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
    fireEvent.mouseDown(screen.getByRole("option", { name: "Alpha" }));
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
  it("stacks its controls full-width when laid out vertically", () => {
    const { container } = renderBar();
    expect(container.firstElementChild).toHaveClass("flex-col", "items-stretch");
  });
});
