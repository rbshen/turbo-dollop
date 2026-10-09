// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import WatchlistPage from "@/app/watchlist/page";
import type { WatchlistOut } from "@/lib/api/types";

afterEach(cleanup);

// Two empty watchlists are enough to exercise the switcher itself --
// WatchlistTable's own empty-tickers early return means no WatchlistRowOut
// fixture is needed here (see WatchlistTable.test.tsx for that shape).
const WATCHLISTS: WatchlistOut[] = [
  {
    id: 1,
    name: "W1",
    sort_field: "ticker",
    sort_direction: "asc",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    tickers: [],
  },
  {
    id: 2,
    name: "W2",
    sort_field: "ticker",
    sort_direction: "asc",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    tickers: [],
  },
];

// Fresh SWRConfig cache per test, matching app/momentum/page.test.tsx's own
// isolation convention.
function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <WatchlistPage />
    </SWRConfig>
  );
}

let fixture: WatchlistOut[] = WATCHLISTS;
let etfRows: unknown[] = [];
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fixture = WATCHLISTS;
  etfRows = [];
  window.localStorage.clear();
  fetchMock = vi.fn(async (url: string) => {
    const body = url.includes("/etf-rows") ? etfRows : url.includes("/rows") ? [] : fixture;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
});

const fetched = (fragment: string) => fetchMock.mock.calls.some(([url]) => String(url).includes(fragment));

// Lists with members, so a table (not the empty-list message) is drawn. "ETF" is the newest, so it opens first.
const withMembers = (name: string, id: number, created: string, tickers: string[]): WatchlistOut => ({
  ...WATCHLISTS[0],
  id,
  name,
  created_at: created,
  tickers: tickers.map((ticker) => ({ ticker, added_at: "2026-01-01T00:00:00Z" })),
});
const ETF_AND_STOCK_LISTS = [
  withMembers("E1", 1, "2026-01-01T00:00:00Z", ["AAPL"]),
  withMembers("W2", 2, "2026-01-02T00:00:00Z", ["MSFT"]),
  withMembers("ETF", 3, "2026-01-03T00:00:00Z", ["SPY", "NEWETF"]),
];
const etfRow = (ticker: string, overrides: Record<string, unknown> = {}) => ({
  ticker, name: null, exchange: null, last_price: null, pct_change_1d: null, asset_class: null, expense_ratio: null, aum: null,
  holdings_count: null, avg_volume_30d: null, dividend_yield: null, beta: null, return_ytd: null, return_1y: null, ...overrides,
});
const bodyTickers = () => [...document.querySelectorAll("tbody tr")].map((tr) => tr.querySelector("td")?.textContent);

describe("WatchlistPage", () => {
  it("defaults to the most recently created watchlist and lists every watchlist as a tab", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("tab", { name: "W2" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("tab", { name: "W1" })).toHaveAttribute("aria-selected", "false");
  });

  it("switches the active watchlist when a different tab is clicked", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("tab", { name: "W2" })).toHaveAttribute("aria-selected", "true"));

    fireEvent.click(screen.getByRole("tab", { name: "W1" }));

    await waitFor(() => expect(screen.getByRole("tab", { name: "W1" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("tab", { name: "W2" })).toHaveAttribute("aria-selected", "false");
  });

  it("offers rename and delete for an ordinary list but neither for the ETF list", async () => {
    fixture = [{ ...WATCHLISTS[0], id: 3, name: "ETF", created_at: "2026-01-03T00:00:00Z" }, WATCHLISTS[1]];
    renderPage();
    // The ETF list is the most recently created, so it is the active tab.
    await waitFor(() => expect(screen.getByRole("tab", { name: "ETF" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.queryByRole("button", { name: /^Rename/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Delete/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "W2" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Rename W2" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^Delete/ })).toBeInTheDocument();
  });

  it("draws the ETF table, and fetches only /etf-rows, for the list named ETF", async () => {
    fixture = ETF_AND_STOCK_LISTS;
    etfRows = [etfRow("SPY", { aum: 8e11 }), etfRow("NEWETF")];
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "Avg Vol 30d" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Moat" })).not.toBeInTheDocument();
    expect(fetched("/watchlists/3/etf-rows")).toBe(true);
    expect(fetched("/watchlists/3/rows")).toBe(false);
  });

  it("keeps the stock table, and fetches only /rows, for E1 and every other list", async () => {
    fixture = ETF_AND_STOCK_LISTS;
    renderPage();
    await waitFor(() => expect(screen.getByRole("tab", { name: "ETF" })).toHaveAttribute("aria-selected", "true"));
    for (const [name, id] of [["E1", 1], ["W2", 2]] as const) {
      fireEvent.click(screen.getByRole("tab", { name }));
      await waitFor(() => expect(screen.getByRole("button", { name: "Moat" })).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: "Avg Vol 30d" })).not.toBeInTheDocument();
      expect(fetched(`/watchlists/${id}/rows`)).toBe(true);
      expect(fetched(`/watchlists/${id}/etf-rows`)).toBe(false);
    }
  });

  it("opens the ETF table sorted by AUM descending, nulls last", async () => {
    fixture = ETF_AND_STOCK_LISTS;
    etfRows = [etfRow("NEWETF"), etfRow("SMALL", { aum: 1e9 }), etfRow("BIG", { aum: 9e11 })];
    renderPage();
    await waitFor(() => expect(bodyTickers()).toEqual(["BIG", "SMALL", "NEWETF"]));
    expect(screen.getByRole("button", { name: "AUM" }).closest("th")).toHaveAttribute("aria-sort", "descending");
  });

  it("persists the ETF table's rules under its own key and leaves the stock key alone", async () => {
    fixture = ETF_AND_STOCK_LISTS;
    etfRows = [etfRow("SPY", { aum: 1 })];
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "Beta" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Beta" }));
    expect(JSON.parse(window.localStorage.getItem("fathom-etf-watchlist-sort-3")!)).toEqual([
      { field: "aum", direction: "desc" },
      { field: "beta", direction: "desc" },
    ]);
    expect(window.localStorage.getItem("fathom-watchlist-sort-3")).toBeNull();
  });

  it("ignores stock-table rules already stored under the ETF list's id, and a foreign value under the ETF key", async () => {
    fixture = ETF_AND_STOCK_LISTS;
    etfRows = [etfRow("SMALL", { aum: 1 }), etfRow("BIG", { aum: 9 })];
    window.localStorage.setItem("fathom-watchlist-sort-3", JSON.stringify([{ field: "moat", direction: "asc" }]));
    window.localStorage.setItem("fathom-etf-watchlist-sort-3", JSON.stringify([{ field: "overall_score", direction: "desc" }]));
    renderPage();
    await waitFor(() => expect(bodyTickers()).toEqual(["BIG", "SMALL"]));
    expect(screen.getByRole("button", { name: "AUM" }).closest("th")).toHaveAttribute("aria-sort", "descending");
  });

  it("restores a valid saved ETF sort on the next visit", async () => {
    fixture = ETF_AND_STOCK_LISTS;
    etfRows = [etfRow("SMALL", { aum: 1 }), etfRow("BIG", { aum: 9 })];
    window.localStorage.setItem("fathom-etf-watchlist-sort-3", JSON.stringify([{ field: "aum", direction: "asc" }]));
    renderPage();
    await waitFor(() => expect(bodyTickers()).toEqual(["SMALL", "BIG"]));
  });

  describe("TradingView export of the ETF table", () => {
    it("writes EXCHANGE:SYMBOL pairs under the Other section, skipping a ticker with no cached exchange", async () => {
      fixture = ETF_AND_STOCK_LISTS;
      etfRows = [etfRow("SPY", { exchange: "AMEX" }), etfRow("QQQ", { exchange: "NASDAQ" }), etfRow("NEWETF")];
      const blobs: Blob[] = [];
      Object.assign(URL, { createObjectURL: (b: Blob) => (blobs.push(b), "blob:x"), revokeObjectURL: () => {} });
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
      renderPage();
      await waitFor(() => expect(screen.getByRole("button", { name: /Export list/ })).not.toBeDisabled());

      fireEvent.click(screen.getByRole("button", { name: /Export list/ }));
      // The single-list items stay disabled until the active list's rows have loaded.
      await waitFor(() => expect(screen.getByRole("menuitem", { name: /TradingView/ })).toBeEnabled());
      fireEvent.click(screen.getByRole("menuitem", { name: /TradingView/ }));

      expect(blobs).toHaveLength(1);
      const text = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsText(blobs[0]);
      });
      expect(text).toBe("###Other,AMEX:SPY,NASDAQ:QQQ");
    });
  });

  describe("Export multiple lists", () => {
    it("opens the inline panel from the Export menu, even while the active list is empty", async () => {
      renderPage();
      const trigger = await screen.findByRole("button", { name: /Export list/ });
      expect(trigger).toBeEnabled();
      fireEvent.click(trigger);
      expect(screen.getByRole("menuitem", { name: /TradingView/ })).toBeDisabled();
      fireEvent.click(screen.getByRole("menuitem", { name: "Export multiple lists…" }));

      const panel = screen.getByRole("region", { name: "Export multiple lists" });
      expect(panel).toBeInTheDocument();
      expect(within(panel).getAllByRole("checkbox").map((el) => el.closest("label")?.textContent)).toEqual(["W1 (0)", "W2 (0)"]);
      fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("region", { name: "Export multiple lists" })).not.toBeInTheDocument();
    });
  });
});
