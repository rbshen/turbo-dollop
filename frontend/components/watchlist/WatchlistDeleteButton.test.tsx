// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WatchlistDeleteButton } from "@/components/watchlist/WatchlistDeleteButton";
import type { WatchlistOut } from "@/lib/api/types";

const deleteWatchlist = vi.fn();
vi.mock("@/lib/hooks/useWatchlists", () => ({
  deleteWatchlist: (...args: unknown[]) => deleteWatchlist(...args),
}));

const WATCHLIST: WatchlistOut = {
  id: 3,
  name: "Growth",
  sort_field: "ticker",
  sort_direction: "asc",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tickers: [],
};

beforeEach(() => {
  deleteWatchlist.mockReset();
  deleteWatchlist.mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("WatchlistDeleteButton", () => {
  it("shows a named trash button when idle", () => {
    render(<WatchlistDeleteButton watchlist={WATCHLIST} onDeleted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Delete Growth" })).toHaveAttribute("title", "Delete watchlist");
  });

  it("asks inline (no window.confirm) and offers Confirm and Cancel", () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    render(<WatchlistDeleteButton watchlist={WATCHLIST} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Growth" }));
    expect(screen.getByText('Delete "Growth"?')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(deleteWatchlist).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("returns to idle without deleting when cancelled", () => {
    const onDeleted = vi.fn();
    render(<WatchlistDeleteButton watchlist={WATCHLIST} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Growth" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Delete Growth" })).toBeInTheDocument();
    expect(deleteWatchlist).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("deletes by id and calls onDeleted when confirmed", async () => {
    const onDeleted = vi.fn();
    render(<WatchlistDeleteButton watchlist={WATCHLIST} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Growth" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(deleteWatchlist).toHaveBeenCalledWith(3);
  });

  it("on failure: no onDeleted, a retry tooltip, then back to a plain tooltip after 3 seconds", async () => {
    vi.useFakeTimers();
    deleteWatchlist.mockRejectedValue(new Error("DELETE failed: 500"));
    const onDeleted = vi.fn();
    render(<WatchlistDeleteButton watchlist={WATCHLIST} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Growth" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await act(async () => {
      await Promise.resolve();
    });
    const button = screen.getByRole("button", { name: "Delete Growth" });
    expect(button).toHaveAttribute("title", "Failed to delete — retry");
    expect(onDeleted).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("button", { name: "Delete Growth" })).toHaveAttribute("title", "Delete watchlist");
  });

  it("uses the destructive Button for Confirm and an outline Button for Cancel, both 36px", () => {
    render(<WatchlistDeleteButton watchlist={WATCHLIST} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Growth" }));
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(confirm).toHaveClass("text-negative", "h-9");
    expect(confirm).not.toHaveClass("border");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveClass("border", "border-border-input", "h-9");
  });

  it("renders the trigger as a 28px icon button with a hidden icon, negative once a delete has failed", async () => {
    deleteWatchlist.mockRejectedValue(new Error("DELETE failed: 500"));
    render(<WatchlistDeleteButton watchlist={WATCHLIST} onDeleted={vi.fn()} />);
    const idle = screen.getByRole("button", { name: "Delete Growth" });
    expect(idle).toHaveClass("size-7", "text-text-tertiary");
    expect(idle.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(idle);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete Growth" })).toHaveClass("text-negative"));
  });
});
