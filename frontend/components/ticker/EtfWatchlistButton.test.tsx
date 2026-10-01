// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EtfWatchlistButton } from "@/components/ticker/EtfWatchlistButton";
import type { WatchlistOut } from "@/lib/api/types";

const addTickerToEtfWatchlist = vi.fn();
let watchlists: WatchlistOut[] | undefined;
vi.mock("@/lib/hooks/useWatchlists", () => ({
  useWatchlists: () => ({ data: watchlists }),
  addTickerToEtfWatchlist: (...args: unknown[]) => addTickerToEtfWatchlist(...args),
}));

function list(id: number, name: string, monitored: boolean, tickers: string[] = []): WatchlistOut {
  return {
    id,
    name,
    sort_field: "ticker",
    sort_direction: "asc",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    tickers: tickers.map((ticker) => ({ ticker, added_at: "2026-01-01T00:00:00Z" })),
    monitored,
  };
}

beforeEach(() => {
  watchlists = [list(1, "Growth", false, ["QQQ"])]; // on an UNMONITORED list only
  addTickerToEtfWatchlist.mockReset().mockResolvedValue({ watchlist_id: 2, watchlist_name: "ETF", added: true });
});
afterEach(cleanup);

describe("EtfWatchlistButton: not on a monitored list", () => {
  it("is the one primary 'Add to watchlist' button, and adds to the ETF list in a single click", async () => {
    render(<EtfWatchlistButton ticker="QQQ" />);
    const button = screen.getByRole("button", { name: "Add to watchlist" });
    expect(button).toHaveClass("bg-brand");

    fireEvent.click(button);

    await waitFor(() => expect(addTickerToEtfWatchlist).toHaveBeenCalledWith("QQQ"));
    expect(addTickerToEtfWatchlist).toHaveBeenCalledTimes(1);
  });

  it("shows no popover or list picker -- the click goes straight to the ETF list", () => {
    render(<EtfWatchlistButton ticker="QQQ" />);
    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    expect(screen.queryByText("New watchlist")).not.toBeInTheDocument();
  });

  it("shows the backend's message when the list is full, and keeps the button usable", async () => {
    addTickerToEtfWatchlist.mockRejectedValue(
      new Error('POST /tickers/QQQ/etf-watchlist failed: 400 - The "ETF" watchlist is full (100/100 tickers). Remove an ETF from it on the Watchlists page, then try again.'),
    );
    render(<EtfWatchlistButton ticker="QQQ" />);
    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/watchlist is full \(100\/100 tickers\)/);
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeEnabled();
  });

  it("disables itself while the request is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    addTickerToEtfWatchlist.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<EtfWatchlistButton ticker="QQQ" />);
    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));

    expect(await screen.findByRole("button", { name: "Adding…" })).toBeDisabled();
    resolve({ watchlist_id: 2, watchlist_name: "ETF", added: true });
  });
});

describe("EtfWatchlistButton: already on a monitored list", () => {
  it("becomes a quiet, non-primary 'On watchlist <name>' with a check icon", () => {
    watchlists = [list(1, "Growth", false, ["QQQ"]), list(2, "ETF", true, ["QQQ"])];
    render(<EtfWatchlistButton ticker="QQQ" />);

    const status = screen.getByRole("button", { name: "On watchlist ETF" });
    expect(status).not.toHaveClass("bg-brand");
    expect(status).toBeDisabled(); // removal stays on the Watchlists page
    expect(status.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("button", { name: "Add to watchlist" })).not.toBeInTheDocument();
  });

  it("names the first list (natural order) plus a count when on several", () => {
    watchlists = [list(1, "E10", true, ["QQQ"]), list(2, "E2", true, ["QQQ"]), list(3, "ETF", true, ["QQQ"])];
    render(<EtfWatchlistButton ticker="QQQ" />);
    expect(screen.getByRole("button", { name: "On watchlist E2 +2" })).toHaveAttribute("title", expect.stringContaining("E2, E10, ETF"));
  });

  it("ignores a monitored list that does not hold this ETF", () => {
    watchlists = [list(1, "ETF", true, ["SMH"])];
    render(<EtfWatchlistButton ticker="QQQ" />);
    expect(screen.getByRole("button", { name: "Add to watchlist" })).toBeInTheDocument();
  });
});
