// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EtfWatchlistTable } from "@/components/watchlist/EtfWatchlistTable";
import type { EtfWatchlistRow, WatchlistOut } from "@/lib/api/types";
import { DEFAULT_ETF_SORT_RULES } from "@/lib/etfWatchlistSort";

const removeTickerFromWatchlist = vi.fn();
vi.mock("@/lib/hooks/useWatchlists", () => ({
  removeTickerFromWatchlist: (...args: unknown[]) => removeTickerFromWatchlist(...args),
}));

afterEach(cleanup);

const WATCHLIST: WatchlistOut = {
  id: 3,
  name: "ETF",
  sort_field: "ticker",
  sort_direction: "asc",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  monitored: true,
  tickers: [
    { ticker: "SPY", added_at: "2026-01-01T00:00:00Z" },
    { ticker: "NEWETF", added_at: "2026-01-02T00:00:00Z" },
    { ticker: "TLT", added_at: "2026-01-03T00:00:00Z" },
  ],
};

function row(ticker: string, overrides: Partial<EtfWatchlistRow> = {}): EtfWatchlistRow {
  return {
    ticker,
    name: null,
    exchange: null,
    last_price: null,
    pct_change_1d: null,
    asset_class: null,
    expense_ratio: null,
    aum: null,
    holdings_count: null,
    avg_volume_30d: null,
    dividend_yield: null,
    beta: null,
    return_ytd: null,
    return_1y: null,
    ...overrides,
  };
}

const SPY = row("SPY", {
  name: "State Street SPDR S&P 500 ETF",
  exchange: "AMEX",
  last_price: 769.64,
  pct_change_1d: 0.74,
  asset_class: "Equity",
  expense_ratio: 0.09,
  aum: 8.1757e11,
  holdings_count: 1986,
  avg_volume_30d: 45_183_836,
  dividend_yield: 0.99,
  beta: 1.01,
  return_ytd: 12.86,
  return_1y: -15.01,
});
const TLT = row("TLT", { name: "iShares 20+ Year Treasury Bond ETF", asset_class: "Fixed Income", aum: 4.7e10, pct_change_1d: -0.3 });
const NEWETF = row("NEWETF");
const ROWS = [SPY, NEWETF, TLT];

function renderTable(props: Partial<Parameters<typeof EtfWatchlistTable>[0]> = {}) {
  return render(
    <EtfWatchlistTable
      watchlist={WATCHLIST}
      rows={ROWS}
      sortRules={DEFAULT_ETF_SORT_RULES}
      onSortRulesChange={vi.fn()}
      {...props}
    />
  );
}

const headers = () => [...document.querySelectorAll("thead th")].map((h) => h.textContent?.trim());
const bodyTickers = () => [...document.querySelectorAll("tbody tr")].map((tr) => tr.querySelector("td")?.textContent);
const cells = (ticker: string) => [...screen.getByText(ticker).closest("tr")!.querySelectorAll("td")].map((td) => td.textContent);

beforeEach(() => removeTickerFromWatchlist.mockReset().mockResolvedValue(undefined));

describe("EtfWatchlistTable columns", () => {
  it("has the 13 headers in order, then an unlabelled remove column", () => {
    renderTable();
    expect(headers()).toEqual([
      "Ticker", "Name", "Price", "% Chg", "Class", "Exp %", "AUM", "Holdings", "Avg Vol 30d", "Yield %", "Beta", "YTD", "1Y", "",
    ]);
  });

  it("formats a full row with the shared formatters", () => {
    renderTable();
    expect(cells("SPY")).toEqual([
      "SPY", "State Street SPDR S&P 500 ETF", "$769.64", "+0.74%", "Equity", "0.09%", "$817.57B", "1,986", "45.18M", "0.99%", "1.01", "+12.86%", "-15.01%", "",
    ]);
  });

  it("colours the signed percentages green and red by sign, and leaves plain figures neutral", () => {
    renderTable();
    const spy = screen.getByText("SPY").closest("tr")!.querySelectorAll("td");
    expect(spy[3].className).toContain("text-positive"); // % Chg
    expect(spy[11].className).toContain("text-positive"); // YTD
    expect(spy[12].className).toContain("text-negative"); // 1Y
    expect(spy[2].className).not.toMatch(/text-(positive|negative)/); // Price
    expect(screen.getByText("TLT").closest("tr")!.querySelectorAll("td")[3].className).toContain("text-negative");
  });

  it("shows a dash for every null figure, and a member with no stored row keeps its ticker", () => {
    renderTable();
    expect(cells("NEWETF")).toEqual(["NEWETF", "–", "–", "–", "–", "–", "–", "–", "–", "–", "–", "–", "–", ""]);
    expect(cells("TLT").slice(2)).toEqual(["–", "-0.30%", "Fixed Income", "–", "$47.00B", "–", "–", "–", "–", "–", "–", ""]);
  });

  it("truncates the name with a title tooltip and the asset class too", () => {
    renderTable();
    const name = screen.getByText("State Street SPDR S&P 500 ETF");
    expect(name.className).toContain("truncate");
    expect(name).toHaveAttribute("title", "State Street SPDR S&P 500 ETF");
  });

  it("gives the Name column the remaining width and the table a minimum width so the fixed columns never squeeze it", () => {
    renderTable();
    expect(screen.getByRole("button", { name: "Name" }).closest("th")!.className).toMatch(/w-full.*min-w-\[140px\]/);
    expect(document.querySelector("table")!.className).toContain("min-w-[1160px]");
    expect(document.querySelector('[data-slot="table-container"]')!.className).toContain("overflow-auto");
  });

  it("keeps every header cell sticky, as the stock table does", () => {
    renderTable();
    for (const cell of document.querySelectorAll("thead th")) {
      expect(cell.className).toContain("sticky");
      expect(cell.className).toContain("bg-page");
    }
  });
});

describe("EtfWatchlistTable sorting", () => {
  it("orders by the given rules, nulls last: the default AUM descending", () => {
    renderTable();
    expect(bodyTickers()).toEqual(["SPY", "TLT", "NEWETF"]);
  });

  it("puts nulls last in ascending order too", () => {
    renderTable({ sortRules: [{ field: "aum", direction: "asc" }] });
    expect(bodyTickers()).toEqual(["TLT", "SPY", "NEWETF"]);
  });

  it("flags the active column with aria-sort and the rest as none", () => {
    renderTable();
    expect(screen.getByRole("button", { name: "AUM" }).closest("th")).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("button", { name: "Beta" }).closest("th")).toHaveAttribute("aria-sort", "none");
  });

  it("reports the next rule list on a header click: append, then flip, like the stock table", () => {
    const onSortRulesChange = vi.fn();
    renderTable({ onSortRulesChange });
    fireEvent.click(screen.getByRole("button", { name: "Beta" }));
    expect(onSortRulesChange).toHaveBeenLastCalledWith([
      { field: "aum", direction: "desc" },
      { field: "beta", direction: "desc" },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "AUM" }));
    expect(onSortRulesChange).toHaveBeenLastCalledWith([{ field: "aum", direction: "asc" }]);
  });

  it("makes all 13 data columns sortable", () => {
    renderTable();
    for (const label of ["Ticker", "Name", "Price", "% Chg", "Class", "Exp %", "AUM", "Holdings", "Avg Vol 30d", "Yield %", "Beta", "YTD", "1Y"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("shows the priority numerals once two rules are active", () => {
    renderTable({ sortRules: [{ field: "beta", direction: "desc" }, { field: "aum", direction: "asc" }] });
    expect(screen.getByRole("button", { name: /Beta/ })).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: /AUM/ })).toHaveTextContent("2");
  });
});

describe("EtfWatchlistTable states", () => {
  it("says so for an empty list", () => {
    renderTable({ watchlist: { ...WATCHLIST, tickers: [] }, rows: [] });
    expect(screen.getByText(/No tickers in this watchlist yet/)).toBeInTheDocument();
  });

  it("shows the load error", () => {
    renderTable({ rows: undefined, error: new Error("boom") });
    expect(screen.getByText(/Couldn.t load this watchlist — boom/)).toBeInTheDocument();
  });

  it("shows pulsing skeleton rows while loading", () => {
    renderTable({ rows: undefined });
    expect(document.querySelectorAll("tbody tr.animate-pulse")).toHaveLength(5);
  });
});

describe("EtfWatchlistTable row actions", () => {
  const openSpy = vi.fn();
  beforeEach(() => {
    openSpy.mockReset();
    vi.stubGlobal("open", openSpy);
  });

  it("opens the ticker page in a new tab when the row is clicked", () => {
    renderTable();
    fireEvent.click(screen.getByText("SPY"));
    expect(openSpy).toHaveBeenCalledWith("/tickers/SPY", "_blank", "noopener,noreferrer");
  });

  it("removes a ticker after the two-step confirm, without opening its page", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Remove SPY" }));
    expect(removeTickerFromWatchlist).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm: remove SPY from ETF" }));
    expect(removeTickerFromWatchlist).toHaveBeenCalledWith(3, "SPY");
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("cancel goes back to the remove button", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Remove TLT" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Remove TLT" })).toBeInTheDocument();
    expect(removeTickerFromWatchlist).not.toHaveBeenCalled();
  });
});
