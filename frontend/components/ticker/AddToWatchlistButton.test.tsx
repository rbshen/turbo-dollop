// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import type { WatchlistOut } from "@/lib/api/types";

const addTickerToWatchlist = vi.fn();
const bulkAddTickersToWatchlist = vi.fn();
const createWatchlist = vi.fn();
const removeTickerFromWatchlist = vi.fn();
let watchlists: WatchlistOut[] | undefined;

vi.mock("@/lib/hooks/useWatchlists", () => ({
  useWatchlists: () => ({ data: watchlists }),
  addTickerToWatchlist: (...args: unknown[]) => addTickerToWatchlist(...args),
  bulkAddTickersToWatchlist: (...args: unknown[]) => bulkAddTickersToWatchlist(...args),
  createWatchlist: (...args: unknown[]) => createWatchlist(...args),
  removeTickerFromWatchlist: (...args: unknown[]) => removeTickerFromWatchlist(...args),
}));

function makeWatchlist(id: number, name: string, tickers: string[] = []): WatchlistOut {
  return {
    id,
    name,
    sort_field: "ticker",
    sort_direction: "asc",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    tickers: tickers.map((ticker) => ({ ticker, added_at: "2026-01-01T00:00:00Z" })),
  };
}

beforeEach(() => {
  watchlists = [makeWatchlist(1, "Growth"), makeWatchlist(2, "Value", ["AAPL"])];
  addTickerToWatchlist.mockReset().mockResolvedValue(undefined);
  bulkAddTickersToWatchlist.mockReset().mockResolvedValue({ added: 2, already_present: 0 });
  createWatchlist.mockReset().mockResolvedValue(makeWatchlist(9, "Fresh"));
  removeTickerFromWatchlist.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

function open(label = "Add to watchlist") {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

describe("AddToWatchlistButton: trigger and popover", () => {
  it("renders the trigger and keeps the popover closed until clicked", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeInTheDocument();
    expect(screen.queryByText("Growth")).not.toBeInTheDocument();
  });

  it("is the 32px primary button: brand fill, h-8 (not the kit's 28px primary sm), a decorative Plus and the word Watchlist", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const trigger = screen.getByRole("button", { name: "Add to watchlist" });
    expect(trigger).toHaveClass("bg-brand", "h-8");
    expect(trigger).not.toHaveClass("h-7");
    expect(trigger).toHaveTextContent("Watchlist");
    expect(trigger.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("shows a custom label as plain text, with no icon and no aria-label of its own", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} label="Add to watchlist" />);
    const trigger = screen.getByRole("button", { name: "Add to watchlist" });
    expect(trigger).not.toHaveAttribute("aria-label");
    expect(trigger.querySelector("svg")).toBeNull();
  });

  it("uses a custom label when given", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} label="Add to watchlist" />);
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeInTheDocument();
  });

  it("honours disabled", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} disabled />);
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeDisabled();
  });

  it("opens on click, lists every watchlist, and toggles closed on a second click", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    expect(screen.getByText("Growth")).toBeInTheDocument();
    expect(screen.getByText("Value")).toBeInTheDocument();
    open();
    expect(screen.queryByText("Growth")).not.toBeInTheDocument();
  });

  it("says so when there are no watchlists yet", () => {
    watchlists = [];
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    expect(screen.getByText("No watchlists yet")).toBeInTheDocument();
  });

  it("says so while the list is still loading", () => {
    watchlists = undefined;
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    expect(screen.getByText("No watchlists yet")).toBeInTheDocument();
  });

  it("closes on an outside click", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText("Growth")).not.toBeInTheDocument();
  });

  it("closes on Escape from inside the popover and returns focus to the trigger", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    const addButton = within(screen.getByText("Growth").parentElement as HTMLElement).getByRole("button", { name: "Add" });
    addButton.focus();
    fireEvent.keyDown(addButton, { key: "Escape" });
    expect(screen.queryByText("Growth")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toHaveFocus();
  });

  it("closes on Escape from the trigger itself", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    const trigger = screen.getByRole("button", { name: "Add to watchlist" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByText("Growth")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("ignores Escape while the popover is closed", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const trigger = screen.getByRole("button", { name: "Add to watchlist" });
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByText("Growth")).not.toBeInTheDocument();
  });

  it("closes a pending confirmation with the popover on Escape", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.keyDown(screen.getByRole("button", { name: "Okay" }), { key: "Escape" });
    open();
    expect(screen.queryByText('Remove AAPL from "Value"?')).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("exposes the open state on the trigger", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const trigger = screen.getByRole("button", { name: "Add to watchlist" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-controls");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const controls = trigger.getAttribute("aria-controls") as string;
    expect(document.getElementById(controls)).toContainElement(screen.getByText("Growth"));
  });

  it("stays open on a click inside the popover", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.mouseDown(screen.getByText("Growth"));
    expect(screen.getByText("Growth")).toBeInTheDocument();
  });
});

describe("AddToWatchlistButton: one ticker", () => {
  it("draws the row buttons as outline buttons, 32px", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    for (const name of ["Add", "Remove"]) {
      expect(screen.getByRole("button", { name })).toHaveClass("border-border-input", "h-8");
    }
  });

  it("adds the ticker to a list and shows the added state", async () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    expect(addTickerToWatchlist).toHaveBeenCalledWith(1, "AAPL");
    const added = await within(row).findByRole("button", { name: "Added" });
    expect(added).toBeDisabled();
    // A Check icon, not a "✓" glyph.
    expect(added.textContent).not.toContain("✓");
    expect(added.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("shows Failed and the server's message when the add is rejected", async () => {
    addTickerToWatchlist.mockRejectedValue(new Error("POST /watchlists/1/tickers failed: 400 - Watchlist is full (100)"));
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    expect(await within(row.parentElement as HTMLElement).findByText("Watchlist is full (100)")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Failed" })).toBeInTheDocument();
  });

  it("falls back to a generic message when the rejection has no detail", async () => {
    addTickerToWatchlist.mockRejectedValue(new Error("network"));
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it("shows Remove (not Add) for a list that already holds the ticker, matching case-insensitively", () => {
    render(<AddToWatchlistButton tickers={["aapl"]} />);
    open();
    const row = screen.getByText("Value").parentElement as HTMLElement;
    expect(within(row).getByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  });

  it("asks before removing, and removes on Okay", async () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByText('Remove AAPL from "Value"?')).toBeInTheDocument();
    expect(removeTickerFromWatchlist).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Okay" }));
    await waitFor(() => expect(removeTickerFromWatchlist).toHaveBeenCalledWith(2, "AAPL"));
    await waitFor(() => expect(screen.queryByText('Remove AAPL from "Value"?')).not.toBeInTheDocument());
  });

  it("goes back to the row when the remove question is cancelled", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText('Remove AAPL from "Value"?')).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(removeTickerFromWatchlist).not.toHaveBeenCalled();
  });

  it("shows the server's message when a remove is rejected", async () => {
    removeTickerFromWatchlist.mockRejectedValue(new Error("DELETE x failed: 500 - Could not remove"));
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Okay" }));
    expect(await screen.findByText("Could not remove")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Failed — retry" })).toBeInTheDocument();
  });
});

describe("AddToWatchlistButton: many tickers", () => {
  const TICKERS = ["AAPL", "MSFT", "NVDA"];

  it("asks before bulk-adding, naming the count", () => {
    render(<AddToWatchlistButton tickers={TICKERS} />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    expect(screen.getByText('Add 3 tickers to "Growth"?')).toBeInTheDocument();
    expect(bulkAddTickersToWatchlist).not.toHaveBeenCalled();
  });

  it("uses the confirmDescription wording when given", () => {
    render(<AddToWatchlistButton tickers={TICKERS} confirmDescription="all 3 filtered tickers" />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    expect(screen.getByText('Add all 3 filtered tickers to "Growth"?')).toBeInTheDocument();
  });

  it("never offers Remove in bulk mode, even for a list that holds one of the tickers", () => {
    render(<AddToWatchlistButton tickers={TICKERS} />);
    open();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("bulk-adds on Okay and reports how many were added", async () => {
    bulkAddTickersToWatchlist.mockResolvedValue({ added: 2, already_present: 1 });
    render(<AddToWatchlistButton tickers={TICKERS} />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Okay" }));
    expect(bulkAddTickersToWatchlist).toHaveBeenCalledWith(1, TICKERS);
    expect(await screen.findByText("Added 2 (1 already in this watchlist)")).toBeInTheDocument();
  });

  it("cancels the bulk question without a request", () => {
    render(<AddToWatchlistButton tickers={TICKERS} />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText('Add 3 tickers to "Growth"?')).not.toBeInTheDocument();
    expect(bulkAddTickersToWatchlist).not.toHaveBeenCalled();
  });

  it("closes a pending bulk question on an outside click", () => {
    render(<AddToWatchlistButton tickers={TICKERS} />);
    open();
    const row = screen.getByText("Growth").parentElement as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Add" }));
    fireEvent.mouseDown(document.body);
    open();
    expect(screen.queryByText('Add 3 tickers to "Growth"?')).not.toBeInTheDocument();
  });
});

describe("AddToWatchlistButton: new watchlist", () => {
  function startNaming() {
    open();
    fireEvent.click(screen.getByRole("button", { name: "New watchlist" }));
    return screen.getByRole("textbox") as HTMLInputElement;
  }

  it("opens a focused naming input with Create and Cancel; creating is disabled while empty", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    expect(input).toHaveFocus();
    expect(screen.getByRole("button", { name: "Create and add" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Create and add" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "Fresh" } });
    expect(screen.getByRole("button", { name: "Create and add" })).toBeEnabled();
  });

  it("creates the list with the trimmed name, adds the ticker to it, and closes the naming step", async () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.change(input, { target: { value: "  Fresh  " } });
    fireEvent.click(screen.getByRole("button", { name: "Create and add" }));
    await waitFor(() => expect(createWatchlist).toHaveBeenCalledWith("Fresh"));
    await waitFor(() => expect(addTickerToWatchlist).toHaveBeenCalledWith(9, "AAPL"));
    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "New watchlist" })).toBeInTheDocument();
  });

  it("creates on Enter", async () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(createWatchlist).toHaveBeenCalledWith("Fresh"));
  });

  it("does nothing on Enter with an empty name", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(createWatchlist).not.toHaveBeenCalled();
  });

  it("bulk-adds every ticker into the new list when there are several", async () => {
    render(<AddToWatchlistButton tickers={["AAPL", "MSFT"]} />);
    const input = startNaming();
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "Create and add" }));
    await waitFor(() => expect(bulkAddTickersToWatchlist).toHaveBeenCalledWith(9, ["AAPL", "MSFT"]));
    expect(addTickerToWatchlist).not.toHaveBeenCalled();
  });

  it("says the name already exists on a 409, keeping the input", async () => {
    createWatchlist.mockRejectedValue(new Error("POST /watchlists failed: 409 - Watchlist name already exists"));
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.change(input, { target: { value: "Growth" } });
    fireEvent.click(screen.getByRole("button", { name: "Create and add" }));
    expect(await screen.findByText('"Growth" already exists')).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Growth");
    expect(addTickerToWatchlist).not.toHaveBeenCalled();
  });

  it("shows the server's own message for any other rejection", async () => {
    createWatchlist.mockRejectedValue(new Error("POST /watchlists failed: 422 - name: too long"));
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "Create and add" }));
    expect(await screen.findByText("name: too long")).toBeInTheDocument();
  });

  it("falls back to a generic message when the rejection has no detail", async () => {
    createWatchlist.mockRejectedValue(new Error("network"));
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "Create and add" }));
    expect(await screen.findByText("Couldn't create watchlist")).toBeInTheDocument();
  });

  it("cancels with the Cancel button, discarding the typed name", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(createWatchlist).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "New watchlist" }));
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("cancels the naming step (only) on Escape in the input", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("Growth")).toBeInTheDocument();
  });

  it("names the input, limits it to the backend's 100 characters and adds no focus:outline-none", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    startNaming();
    const input = screen.getByRole("textbox", { name: "New watchlist name" });
    expect(input).toHaveAttribute("maxlength", "100");
    expect(input.className).not.toContain("outline-none");
  });

  it("links a server rejection to the input as an alert and marks the input invalid", async () => {
    createWatchlist.mockRejectedValue(new Error("POST /watchlists failed: 422 - name: too long"));
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    const input = startNaming();
    expect(input).not.toHaveAttribute("aria-invalid");
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "Create and add" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("name: too long");
    const field = screen.getByRole("textbox", { name: "New watchlist name" });
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAttribute("aria-describedby", alert.id);
  });

  it("makes Create and add the one primary button and Cancel an outline button", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    startNaming();
    expect(screen.getByRole("button", { name: "Create and add" })).toHaveClass("bg-brand");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("border-border-input");
  });
});

describe("AddToWatchlistButton: the naming step's focus", () => {
  function startNaming() {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "New watchlist" }));
  }

  it("moves focus into the name box when the step opens", () => {
    startNaming();
    expect(screen.getByRole("textbox", { name: "New watchlist name" })).toHaveFocus();
  });

  it("returns focus to the 'New watchlist' button after Cancel", () => {
    startNaming();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "New watchlist name" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New watchlist" })).toHaveFocus();
  });

  it("returns focus there after Escape in the name box too, without closing the popover", () => {
    startNaming();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "New watchlist name" }), { key: "Escape" });
    expect(screen.getByRole("button", { name: "New watchlist" })).toHaveFocus();
    expect(screen.getByText("Growth")).toBeInTheDocument();
  });

  it("does not pull focus anywhere when the popover is closed without a naming step", () => {
    render(<AddToWatchlistButton tickers={["AAPL"]} />);
    open();
    fireEvent.mouseDown(document.body);
    expect(screen.getByRole("button", { name: "Add to watchlist" })).not.toHaveFocus();
  });
});
