// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScreenerResultsControlsMock } from "./ScreenerResultsControlsMock";

afterEach(cleanup);

// Smoke tests: the results-controls reference renders from mock data alone, shows
// every state the brief lists, and the real components inside it behave.
const frame = (id: string) => within(screen.getByTestId(id));

describe("ScreenerResultsControlsMock: Sort row", () => {
  it("renders the real Sort row twice (results width and 320px) with the labelled wide select", () => {
    render(<ScreenerResultsControlsMock />);
    const selects = screen.getAllByLabelText("Sort by") as HTMLSelectElement[];
    expect(selects).toHaveLength(2);
    for (const s of selects) {
      expect(s.options).toHaveLength(12);
      expect(s.parentElement).toHaveClass("w-80", "max-w-full");
    }
    expect(screen.getAllByRole("button", { name: /^Sort direction: descending\. Switch to ascending\.$/ })).toHaveLength(2);
  });

  it("the direction toggle and the field work independently in each row", () => {
    render(<ScreenerResultsControlsMock />);
    const [first, second] = screen.getAllByRole("button", { name: /^Sort direction:/ });
    fireEvent.click(first);
    expect(first).toHaveAccessibleName("Sort direction: ascending. Switch to descending.");
    expect(second).toHaveAccessibleName("Sort direction: descending. Switch to ascending.");
    const [select] = screen.getAllByLabelText("Sort by") as HTMLSelectElement[];
    fireEvent.change(select, { target: { value: "beta" } });
    expect(select.value).toBe("beta");
  });
});

describe("ScreenerResultsControlsMock: Pagination", () => {
  it("shows the first, a middle and the last page", () => {
    render(<ScreenerResultsControlsMock />);
    const first = frame("pager-1-of-10");
    const middle = frame("pager-5-of-10");
    const last = frame("pager-10-of-10");
    expect(first.getByRole("button", { name: "1" })).toHaveAttribute("aria-current", "page");
    expect(first.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(first.getByRole("button", { name: "Next page" })).toBeEnabled();
    expect(middle.getByRole("button", { name: "5" })).toHaveAttribute("aria-current", "page");
    expect(middle.getByRole("button", { name: "Previous page" })).toBeEnabled();
    expect(middle.getByRole("button", { name: "Next page" })).toBeEnabled();
    expect(last.getByRole("button", { name: "10" })).toHaveAttribute("aria-current", "page");
    expect(last.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("the current page is neutral, never brand, and moves when another page is clicked", () => {
    render(<ScreenerResultsControlsMock />);
    const middle = frame("pager-5-of-10");
    expect(middle.getByRole("button", { name: "5" })).toHaveClass("bg-surface-2", "text-text-primary");
    fireEvent.click(middle.getByRole("button", { name: "Next page" }));
    expect(middle.getByRole("button", { name: "6" })).toHaveAttribute("aria-current", "page");
    expect(middle.getByRole("button", { name: "5" })).not.toHaveAttribute("aria-current");
    expect(screen.getByTestId("pagination-section").innerHTML).not.toContain("bg-brand");
  });
});

describe("ScreenerResultsControlsMock: saved-views bar", () => {
  it("shows an idle bar with the list count", () => {
    render(<ScreenerResultsControlsMock />);
    const idle = frame("bar-idle");
    expect(idle.getByRole("button", { name: "Saved views (4)" })).toHaveAttribute("aria-expanded", "false");
    expect(idle.getByRole("button", { name: "Save current view" })).toBeInTheDocument();
    expect(idle.getByRole("button", { name: "Reset" })).toBeInTheDocument();
  });

  it("shows the popover open with the list and an active view, neutral and marked with aria-current", () => {
    render(<ScreenerResultsControlsMock />);
    const open = frame("bar-open");
    const list = within(open.getByRole("group", { name: "Saved views" }));
    expect(list.getAllByRole("button", { name: (n) => !n.startsWith("Delete view") })).toHaveLength(4);
    const active = list.getByRole("button", { name: "Quality compounders" });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(active.outerHTML).not.toContain("brand");
    expect(list.getByRole("button", { name: 'Delete view "Stage 2 breakouts"' })).toBeInTheDocument();
  });

  it("Escape closes the open popover and returns focus to its trigger", () => {
    render(<ScreenerResultsControlsMock />);
    const open = frame("bar-open");
    const row = open.getByRole("button", { name: "Stage 2 breakouts" });
    row.focus();
    fireEvent.keyDown(row, { key: "Escape" });
    expect(open.queryByRole("group", { name: "Saved views" })).toBeNull();
    expect(open.getByRole("button", { name: /^Quality compounders/ })).toHaveFocus();
  });

  it.each([
    ["bar-naming-222", 222],
    ["bar-naming-256", 256],
  ])("shows the naming step at %s (%ipx) with a labelled full-width input and the buttons below", (id, width) => {
    render(<ScreenerResultsControlsMock />);
    const bar = frame(id);
    const input = bar.getByLabelText("View name") as HTMLInputElement;
    expect(input.value).toBe("Stage 2 leaders");
    expect(input).toHaveClass("w-full");
    expect(screen.getByTestId(id).querySelector("[style]")).toHaveStyle({ width: `${width}px` });
    const save = bar.getByRole("button", { name: "Save" });
    expect(save.parentElement).toBe(bar.getByRole("button", { name: "Cancel" }).parentElement);
    expect(input.compareDocumentPosition(save) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the '/' error in the naming step and keeps Save off", () => {
    render(<ScreenerResultsControlsMock />);
    const bar = frame("bar-naming-slash");
    expect(bar.getByRole("alert")).toHaveTextContent('A view name cannot contain "/".');
    expect(bar.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("shows the overwrite confirm with the message above the buttons", () => {
    render(<ScreenerResultsControlsMock />);
    const bar = frame("bar-overwrite");
    const message = bar.getByText(/already exists/);
    const overwrite = bar.getByRole("button", { name: "Overwrite" });
    expect(message.parentElement).toHaveClass("flex-col");
    expect(message.compareDocumentPosition(overwrite) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("saves into the in-memory list only, and deletes from it", async () => {
    render(<ScreenerResultsControlsMock />);
    const bar = frame("bar-naming-222");
    fireEvent.change(bar.getByLabelText("View name"), { target: { value: "Brand new view" } });
    await act(async () => {
      fireEvent.click(bar.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(bar.getByRole("button", { name: "Brand new view" })).toBeInTheDocument());
    const open = frame("bar-open");
    await act(async () => {
      fireEvent.click(open.getByRole("button", { name: 'Delete view "Cheap with low debt"' }));
    });
    await waitFor(() => expect(open.queryByRole("button", { name: "Cheap with low debt" })).toBeNull());
  });
});

describe("ScreenerResultsControlsMock: multi-select trigger", () => {
  it("shows none, one and several selected, each with its '<label>: <summary>' name", () => {
    render(<ScreenerResultsControlsMock />);
    expect(frame("multi-0").getByRole("button", { name: "Sector: none selected" })).toHaveTextContent("Sector");
    expect(frame("multi-1").getByRole("button", { name: "Sector: Technology" })).toHaveTextContent("Technology");
    expect(frame("multi-3").getByRole("button", { name: "Sector: 3 selected" })).toHaveTextContent("Sector (3)");
  });

  it("opens into the real checkbox popover", () => {
    render(<ScreenerResultsControlsMock />);
    fireEvent.click(frame("multi-0").getByRole("button", { name: "Sector: none selected" }));
    expect(screen.getByRole("listbox", { name: "Sector" })).toBeInTheDocument();
  });
});

describe("ScreenerResultsControlsMock: computed sizes", () => {
  it("says the sizes are computed, not measured, and states the sort select decision", () => {
    render(<ScreenerResultsControlsMock />);
    const note = screen.getByTestId("results-metrics-note");
    expect(note).toHaveTextContent("not measured in a browser");
    expect(note).toHaveTextContent("Warren signal recency");
    expect(note).toHaveTextContent("fits (chosen)");
    expect(note).toHaveTextContent("of 222px");
  });
});
