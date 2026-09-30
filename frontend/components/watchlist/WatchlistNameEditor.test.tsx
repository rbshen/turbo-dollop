// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WatchlistNameEditor } from "@/components/watchlist/WatchlistNameEditor";
import type { WatchlistOut } from "@/lib/api/types";
import { WATCHLIST_NAME_MAX_LENGTH } from "@/lib/watchlistName";

const updateWatchlist = vi.fn();
vi.mock("@/lib/hooks/useWatchlists", () => ({
  updateWatchlist: (...args: unknown[]) => updateWatchlist(...args),
}));

const WATCHLIST: WatchlistOut = {
  id: 7,
  name: "Growth",
  sort_field: "ticker",
  sort_direction: "asc",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tickers: [
    { ticker: "AAPL", added_at: "2026-01-01T00:00:00Z" },
    { ticker: "MSFT", added_at: "2026-01-01T00:00:00Z" },
  ],
};

beforeEach(() => {
  updateWatchlist.mockReset();
  updateWatchlist.mockResolvedValue(undefined);
});
afterEach(cleanup);

function startEditing() {
  fireEvent.click(screen.getByRole("button", { name: "Rename Growth" }));
  return screen.getByRole("textbox", { name: "Watchlist name" }) as HTMLInputElement;
}

describe("WatchlistNameEditor", () => {
  it("shows the name and ticker count with a named rename button when idle", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    expect(screen.getByText("Growth · 2 tickers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename Growth" })).toHaveAttribute("title", "Rename watchlist");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("uses the singular for exactly one ticker", () => {
    render(<WatchlistNameEditor watchlist={{ ...WATCHLIST, tickers: [WATCHLIST.tickers[0]] }} />);
    expect(screen.getByText("Growth · 1 ticker")).toBeInTheDocument();
  });

  it("swaps to a focused input holding the current name, with Save and Cancel", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    expect(input).toHaveValue("Growth");
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("maxlength", "100");
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("saves the trimmed name, then returns to the idle display", async () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "  Value  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(updateWatchlist).toHaveBeenCalledWith(7, { name: "Value" });
  });

  it("saves on Enter", async () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Value" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(updateWatchlist).toHaveBeenCalledWith(7, { name: "Value" }));
  });

  it("cancels on the Cancel button and restores the original name on the next edit", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Something else" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(updateWatchlist).not.toHaveBeenCalled();
    expect(startEditing()).toHaveValue("Growth");
  });

  it("cancels on Escape without saving", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Something else" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(updateWatchlist).not.toHaveBeenCalled();
  });

  it("rejects an empty (or whitespace-only) name without calling the server", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Name can't be empty")).toBeInTheDocument();
    expect(updateWatchlist).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Watchlist name" })).toBeInTheDocument();
  });

  it("rejects a name over 100 characters without calling the server", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    // fireEvent bypasses the input's maxLength, the same way a paste could.
    fireEvent.change(input, { target: { value: "x".repeat(101) } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Name must be 100 characters or fewer")).toBeInTheDocument();
    expect(updateWatchlist).not.toHaveBeenCalled();
  });

  it("accepts exactly 100 characters", async () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "x".repeat(100) } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateWatchlist).toHaveBeenCalledWith(7, { name: "x".repeat(100) }));
  });

  it("closes without a request when the trimmed name is unchanged", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "  Growth " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(updateWatchlist).not.toHaveBeenCalled();
  });

  it("disables the controls and shows Saving… while the request is in flight", async () => {
    let resolve: () => void = () => {};
    updateWatchlist.mockReturnValue(new Promise<void>((r) => (resolve = r)));
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Watchlist name" })).toBeDisabled();
    resolve();
    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
  });

  it("shows a duplicate-name message on a 409 and stays in editing", async () => {
    updateWatchlist.mockRejectedValue(new Error("PUT /watchlists/7 failed: 409 - Watchlist name already exists"));
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText('"Value" already exists')).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Watchlist name" })).toHaveValue("Value");
  });

  it("shows the server's own message for any other rejection", async () => {
    updateWatchlist.mockRejectedValue(new Error("PUT /watchlists/7 failed: 422 - name: String should have at most 100 characters"));
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("name: String should have at most 100 characters")).toBeInTheDocument();
  });

  it("falls back to a generic message when the failure carries no server detail", async () => {
    updateWatchlist.mockRejectedValue(new Error("Failed to fetch"));
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Couldn't rename watchlist")).toBeInTheDocument();
  });

  it("uses the kit Input untouched (36px boxed, wide, no focus override) and outline Save and Cancel", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    expect(input.className).toContain("h-9");
    expect(input.className).toContain("w-80");
    expect(input.className).not.toContain("focus:outline-none");
    expect(input.className).not.toContain("h-7");
    for (const name of ["Save", "Cancel"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveClass("border", "border-border-input", "h-9");
      expect(button.className).not.toContain("h-7");
    }
  });

  it("marks the input invalid and links the alert to it while an error shows", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const input = startEditing();
    expect(input).not.toHaveAttribute("aria-invalid");
    fireEvent.change(input, { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Name can't be empty");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", alert.id);
  });

  it("makes the rename trigger a 28px ghost icon button with a hidden icon", () => {
    render(<WatchlistNameEditor watchlist={WATCHLIST} />);
    const button = screen.getByRole("button", { name: "Rename Growth" });
    expect(button).toHaveClass("size-7");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("mirrors the backend limit through the shared constant", () => {
    expect(WATCHLIST_NAME_MAX_LENGTH).toBe(100);
  });
});
