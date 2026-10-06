// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WatchlistTable } from "@/components/watchlist/WatchlistTable";
import type { WatchlistOut, WatchlistRowOut } from "@/lib/api/types";
import { DEFAULT_SORT_RULES } from "@/lib/watchlistSort";

const removeTickerFromWatchlist = vi.fn();
vi.mock("@/lib/hooks/useWatchlists", () => ({
  removeTickerFromWatchlist: (...args: unknown[]) => removeTickerFromWatchlist(...args),
}));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const WATCHLIST: WatchlistOut = {
  id: 1,
  name: "W1",
  sort_field: "ticker",
  sort_direction: "asc",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tickers: [{ ticker: "AAPL", added_at: "2026-01-01T00:00:00Z" }],
};

const ROWS: WatchlistRowOut[] = [
  {
    ticker: "AAPL",
    company_name: "Apple Inc.",
    sector: "Technology",
    exchange: "NASDAQ",
    years: ["2022", "2023", "2024", "2025", "TTM"],
    revenue: [1, 2, 3, 4, 5],
    net_income: [1, 2, 3, 4, 5],
    cfo: [1, 2, 3, 4, 5],
    moat: "wide_moat",
    valuation_verdict: "undervalued",
    valuation_source: "auto",
    step1_score: 90,
    step1_verdict: "Pass",
    step2_score: 90,
    step2_verdict: "Pass",
    step4_score: 90,
    step4_verdict: "Pass",
    step5_score: 90,
    step5_verdict: "Pass",
    overall_score: 90,
    overall_verdict: "Pass",
    last_price: 187.25,
    market_cap: 3_000_000_000_000,
    quote_currency: "USD",
    reported_currency: "USD",
    pe_ratio: 30,
    beta: 1.2,
    perf_5y_vs_spy_pct: null,
    perf_5y_vs_spy_status: null,
    speculative_growth_qualifies: false,
    consensus_rating: "Buy",
    added_at: "2026-01-01T00:00:00Z",
  },
];

describe("WatchlistTable Last column", () => {
  it("shows the last price right after Sector, and nothing when uncached", () => {
    render(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={[ROWS[0], { ...ROWS[0], ticker: "NOPX", last_price: null }]}
        sortRules={DEFAULT_SORT_RULES}
        onSortRulesChange={vi.fn()}
      />
    );
    const headers = [...document.querySelectorAll("thead th")].map((h) => h.textContent?.trim());
    expect(headers.indexOf("Last")).toBe(headers.indexOf("Sector") + 1);
    const col = headers.indexOf("Last");
    expect(screen.getByText("AAPL").closest("tr")!.querySelectorAll("td")[col]).toHaveTextContent("$187.25");
    expect(screen.getByText("NOPX").closest("tr")!.querySelectorAll("td")[col]).toHaveTextContent(/^$/);
  });
});

describe("WatchlistTable sticky header", () => {
  // bg-page (not a visible surface fill) -- 2026-09-28 design-system change:
  // a sticky header only needs to paint over scrolled-under rows, not draw
  // its own card-like fill the way the old bg-surface-2 did.
  it("keeps every column header cell sticky with a solid background", () => {
    render(
      <WatchlistTable watchlist={WATCHLIST} rows={ROWS} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />
    );
    for (const cell of document.querySelectorAll("thead th")) {
      expect(cell.className).toContain("sticky");
      expect(cell.className).toContain("top-0");
      expect(cell.className).toContain("bg-page");
    }
  });

  it("gives the table its own bounded, two-axis scroll box (not just overflow-x)", () => {
    // Regression guard: a container with only `overflow-x-auto` set forces
    // `overflow-y` to compute as `auto` too (per the CSS overflow spec),
    // silently making that div -- not the window -- the sticky positioning
    // context. Since the div's own top edge sits at the header's natural
    // position, this used to make `top-0`/`top-12` "stuck" immediately,
    // producing a permanent blank gap instead of a working sticky header.
    render(
      <WatchlistTable watchlist={WATCHLIST} rows={ROWS} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />
    );
    const container = document.querySelector('[data-slot="table-container"]');
    expect(container?.className).toContain("overflow-auto");
    expect(container?.className).toMatch(/max-h-/);
  });

  it("still cycles sort rules when a sticky header is clicked", () => {
    const onSortRulesChange = vi.fn();
    render(
      <WatchlistTable watchlist={WATCHLIST} rows={ROWS} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={onSortRulesChange} />
    );
    screen.getByRole("button", { name: "Moat" }).click();
    expect(onSortRulesChange).toHaveBeenCalledTimes(1);
  });

  it("exposes aria-sort on the active sortable header and updates it when direction flips", () => {
    const { rerender } = render(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={ROWS}
        sortRules={[{ field: "moat", direction: "asc" }]}
        onSortRulesChange={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: "Moat" }).closest("th")).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByRole("button", { name: "Sector" }).closest("th")).toHaveAttribute("aria-sort", "none");

    rerender(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={ROWS}
        sortRules={[{ field: "moat", direction: "desc" }]}
        onSortRulesChange={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: "Moat" }).closest("th")).toHaveAttribute("aria-sort", "descending");
  });
});

describe("WatchlistTable remove button", () => {
  const openSpy = vi.fn();

  beforeEach(() => {
    removeTickerFromWatchlist.mockReset();
    removeTickerFromWatchlist.mockResolvedValue(undefined);
    openSpy.mockReset();
    vi.stubGlobal("open", openSpy);
  });

  function renderTable() {
    render(<WatchlistTable watchlist={WATCHLIST} rows={ROWS} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />);
  }

  it("shows a named remove button on each row", () => {
    renderTable();
    expect(screen.getByRole("button", { name: "Remove AAPL" })).toHaveAttribute("title", "Remove AAPL");
  });

  it("asks first: Confirm and Cancel replace the remove button, and nothing is removed yet", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL" }));
    expect(screen.getByRole("button", { name: "Confirm: remove AAPL from W1" })).toHaveAttribute("title", "Remove AAPL from W1?");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove AAPL" })).not.toBeInTheDocument();
    expect(removeTickerFromWatchlist).not.toHaveBeenCalled();
  });

  it("goes back to the remove button when cancelled", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Remove AAPL" })).toBeInTheDocument();
    expect(removeTickerFromWatchlist).not.toHaveBeenCalled();
  });

  it("removes the ticker from this watchlist when confirmed", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm: remove AAPL from W1" }));
    expect(removeTickerFromWatchlist).toHaveBeenCalledWith(1, "AAPL");
  });

  it("does not open the ticker page when any of the three buttons is clicked", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm: remove AAPL from W1" }));
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("still opens the ticker page when the row itself is clicked", () => {
    renderTable();
    fireEvent.click(screen.getByText("Apple Inc."));
    expect(openSpy).toHaveBeenCalledWith("/tickers/AAPL", "_blank", "noopener,noreferrer");
  });

  it("on failure shows a retry tooltip, then resets after 4 seconds", async () => {
    vi.useFakeTimers();
    removeTickerFromWatchlist.mockRejectedValue(new Error("DELETE failed: 500"));
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm: remove AAPL from W1" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "Remove AAPL" })).toHaveAttribute("title", "Failed to remove — retry");
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.getByRole("button", { name: "Remove AAPL" })).toHaveAttribute("title", "Remove AAPL");
  });

  it("draws the three buttons as 32px outline icon buttons with hidden icons and no text glyphs", () => {
    renderTable();
    const remove = screen.getByRole("button", { name: "Remove AAPL" });
    expect(remove).toHaveClass("size-8", "border", "border-border-input");
    expect(remove.textContent).toBe("");
    expect(remove.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(remove);
    for (const name of ["Confirm: remove AAPL from W1", "Cancel"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveClass("size-8", "border");
      expect(button.textContent).toBe("");
      expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    }
  });
});

describe("WatchlistTable: Moat not rated", () => {
  it("draws the steps-only score in a neutral pill with the reason as its tooltip", () => {
    const unrated: WatchlistRowOut = { ...ROWS[0], ticker: "WSM", moat: null, overall_score: 81, overall_verdict: "moat_not_rated" };
    render(<WatchlistTable watchlist={WATCHLIST} rows={[ROWS[0], unrated]} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />);
    const cell = (ticker: string) => (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[8];
    const pill = cell("WSM").querySelector("span[title]") as HTMLElement;
    expect(pill).toHaveTextContent("81");
    expect(pill).toHaveAttribute("title", "Moat not rated: rate the moat to enable a Pass");
    expect(pill).toHaveClass("text-text-secondary");
    expect(cell("AAPL").querySelector("span[title]")).toBeNull(); // a rated Pass is unchanged
  });
});

describe("WatchlistTable: ETF rows", () => {
  const ETF_ROW: WatchlistRowOut = {
    ...ROWS[0],
    ticker: "QQQ",
    company_name: "Invesco QQQ Trust",
    sector: null,
    moat: null,
    valuation_verdict: null,
    valuation_source: null,
    overall_score: null,
    overall_verdict: null,
    years: [],
    revenue: [],
    net_income: [],
    cfo: null,
    last_price: null,
    market_cap: null,
    pe_ratio: null,
    beta: null,
    consensus_rating: "N/A",
    is_etf: true,
  };

  function analysisCell(ticker: string) {
    const row = screen.getByText(ticker).closest("tr") as HTMLElement;
    return row.querySelectorAll("td")[8]; // Ticker, Sector, Last, Rev, NI, CFO, Moat, Value, Analysis
  }

  it("shows an ETF marker in the Analysis cell instead of the blank/missing score", () => {
    render(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={[ROWS[0], ETF_ROW]}
        sortRules={DEFAULT_SORT_RULES}
        onSortRulesChange={vi.fn()}
      />,
    );
    expect(analysisCell("QQQ")).toHaveTextContent("ETF");
    expect(analysisCell("QQQ")).not.toHaveTextContent("—");
    expect(analysisCell("AAPL")).toHaveTextContent("90"); // a stock row is unchanged
    expect(analysisCell("AAPL")).not.toHaveTextContent("ETF");
  });

  it("shows a dash in the Rating cell of an ETF row, while a stock row keeps its rating", () => {
    render(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={[ROWS[0], ETF_ROW]}
        sortRules={DEFAULT_SORT_RULES}
        onSortRulesChange={vi.fn()}
      />,
    );
    const ratingCell = (ticker: string) =>
      (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[9]; // ... Analysis, Rating
    expect(ratingCell("QQQ")).toHaveTextContent("—");
    expect(ratingCell("QQQ")).not.toHaveTextContent("N/A");
    expect(ratingCell("AAPL")).toHaveTextContent("BUY");
  });

  it("an unscored non-ETF still shows the missing dash, not the marker", () => {
    render(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={[{ ...ETF_ROW, is_etf: false }]}
        sortRules={DEFAULT_SORT_RULES}
        onSortRulesChange={vi.fn()}
      />,
    );
    expect(analysisCell("QQQ")).toHaveTextContent("—");
  });
});

describe("WatchlistTable width", () => {
  const renderTable = () =>
    render(
      <WatchlistTable watchlist={WATCHLIST} rows={ROWS} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={() => {}} />,
    );

  it("narrows Ticker and Sector and carries no min-width that forces a horizontal scroll", () => {
    const { container } = renderTable();
    expect(container.querySelector("table")?.className).not.toMatch(/min-w-/);
    const ticker = screen.getByRole("button", { name: "Ticker" }).closest("th");
    const sector = screen.getByRole("button", { name: "Sector" }).closest("th");
    expect(ticker?.className).toContain("w-[150px]");
    expect(sector?.className).toContain("w-[140px]");
    expect(container.innerHTML).not.toContain("250px");
  });

  it("truncates the sector with its full name in the tooltip, and never wraps the monospace ticker", () => {
    renderTable();
    const sector = screen.getByText("Technology");
    expect(sector.className).toContain("truncate");
    expect(sector).toHaveAttribute("title", "Technology");
    expect(screen.getByText("AAPL").className).toMatch(/font-mono.*whitespace-nowrap/);
  });
});
