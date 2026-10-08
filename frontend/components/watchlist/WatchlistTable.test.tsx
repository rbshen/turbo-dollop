// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { overallCellTitle, WatchlistTable } from "@/components/watchlist/WatchlistTable";
import type { WatchlistOut, WatchlistRowOut } from "@/lib/api/types";
import { DEFAULT_SORT_RULES, sortWatchlistRows } from "@/lib/watchlistSort";

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
  it("draws the score in its normal verdict tone with the note as its tooltip (scored as No moat)", () => {
    const unrated: WatchlistRowOut = { ...ROWS[0], ticker: "WSM", moat: null, overall_score: 56, overall_verdict: "Fail" };
    render(<WatchlistTable watchlist={WATCHLIST} rows={[ROWS[0], unrated]} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />);
    const cell = (ticker: string) => (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[8];
    const pill = cell("WSM").querySelector("span[title]") as HTMLElement;
    expect(pill).toHaveTextContent("56");
    expect(pill).toHaveAttribute("title", "Moat not rated, scored as No moat");
    expect(pill).toHaveClass("text-not-pass"); // a Fail, not a neutral "not rated" pill
    expect(cell("AAPL").querySelector("span[title]")).toBeNull(); // a rated Pass is unchanged
  });
});

describe("WatchlistTable: Pass with caution tooltip names its reason", () => {
  const caution = (overrides: Partial<WatchlistRowOut>): WatchlistRowOut => ({ ...ROWS[0], overall_verdict: "Pass with caution", overall_score: 80, ...overrides });

  it("names the weak step when a step is below the pass line", () => {
    expect(overallCellTitle(caution({ step4_score: 60, step4_verdict: "Fail" }))).toBe("Profitability may not pass");
  });

  it("names several weak steps, and a weak step is read from the score as well as a stored Fail", () => {
    expect(overallCellTitle(caution({ step1_score: 65, step1_verdict: "Fail", step5_score: 55, step5_verdict: "Fail" }))).toBe("Financials, Debt may not pass");
  });

  it("names both reasons when a Debt caution and a weak step apply together", () => {
    expect(overallCellTitle(caution({ step5_score: 74, step5_verdict: "Pass with caution", step2_score: 50, step2_verdict: "Fail" }))).toBe(
      "Passed with caution: Debt. Growth Rate may not pass",
    );
  });

  it("keeps the Debt-only text for a step caution alone, and ignores a missing (exempt) score", () => {
    expect(overallCellTitle(caution({ step5_score: 74, step5_verdict: "Pass with caution" }))).toBe("Passed with caution: Debt");
    expect(overallCellTitle(caution({ step5_score: null, step5_verdict: "not_supported" }))).toBe("Passed with caution");
  });

  it("adds nothing to a plain Pass or a Fail", () => {
    expect(overallCellTitle({ ...ROWS[0], step4_score: 60, step4_verdict: "Fail" })).toBeUndefined();
    expect(overallCellTitle({ ...ROWS[0], overall_verdict: "Fail", overall_score: 50, step4_score: 60, step4_verdict: "Fail" })).toBeUndefined();
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

describe("WatchlistTable: Review marker", () => {
  const REASON = {
    step: "step5" as const,
    score: 43,
    verdict: "Fail",
    hint: "unclear" as const,
    raw_hint: "unclear" as const,
    guarded: false,
    rule: "not_covered",
    evidence: "Current Ratio 0.78 (borderline_fail): below 1.0 in 1 of the last 5 fiscal years and 5 of the last 8 quarters",
  };
  const reviewed = (ticker: string, status: WatchlistRowOut["review_status"], extra: Partial<WatchlistRowOut> = {}): WatchlistRowOut => ({
    ...ROWS[0],
    ticker,
    company_name: `${ticker} Corp`,
    overall_score: 71,
    overall_verdict: "Pass",
    review_status: status,
    review_reasons: status ? [REASON] : null,
    conviction: status ? "high" : null,
    ...extra,
  });
  const analysisCell = (ticker: string) =>
    (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[8] as HTMLElement;
  const renderRows = (rows: WatchlistRowOut[], sortRules = DEFAULT_SORT_RULES) =>
    render(<WatchlistTable watchlist={WATCHLIST} rows={rows} sortRules={sortRules} onSortRulesChange={vi.fn()} />);

  it.each([
    ["review_structural", "Review (structural)"],
    ["review_unclear", "Review (unclear)"],
    ["review_by_design", "Review (by design)"],
    ["data_uncertain", "Data uncertain"],
  ] as const)("%s draws an icon-only marker in the Analysis cell with the shared tooltip", (status, label) => {
    renderRows([reviewed("HCA", status)]);
    const marker = analysisCell("HCA").querySelector("[data-testid='review-marker']") as HTMLElement;
    expect(marker).not.toBeNull();
    expect(marker).toHaveTextContent(label); // screen-reader text only
    expect(marker.querySelector(".sr-only")).not.toBeNull();
    expect(marker.getAttribute("title")).toBe(
      `Overall 71 would read Pass. Debt scored 43 (May not pass). ${REASON.evidence}. Conviction: high.`,
    );
  });

  it("keeps the score pill exactly as it was beside the marker (a Pass stays a Pass, the caution glyph stays)", () => {
    renderRows([reviewed("HCA", "review_unclear"), reviewed("GE", "review_unclear", { overall_verdict: "Pass with caution", overall_score: 73, step5_verdict: "Pass with caution" })]);
    expect(analysisCell("HCA")).toHaveTextContent("71");
    expect(analysisCell("GE")).toHaveTextContent("73 ⚠");
    // the pill's own tooltip (caution steps) is untouched by the marker
    expect(analysisCell("GE").querySelector("span[title^='Passed with caution']")).not.toBeNull();
    expect(analysisCell("GE").querySelector("[data-testid='review-marker']")).not.toBeNull();
  });

  it("renders no marker for a row without a status (and nothing else changes in its cell)", () => {
    renderRows([reviewed("MSFT", null), ROWS[0]]);
    expect(analysisCell("MSFT").querySelector("[data-testid='review-marker']")).toBeNull();
    expect(analysisCell("MSFT").children).toHaveLength(1); // the pill only
    expect(analysisCell("AAPL").querySelector("[data-testid='review-marker']")).toBeNull();
  });

  it("an ETF row never shows a marker, even if a payload carried a status", () => {
    renderRows([reviewed("QQQ", "review_unclear", { is_etf: true, overall_score: null, overall_verdict: null })]);
    expect(analysisCell("QQQ")).toHaveTextContent("ETF");
    expect(analysisCell("QQQ").querySelector("[data-testid='review-marker']")).toBeNull();
  });

  it("does not make the column any wider through fixed widths: the Analysis header and cell carry no width class", () => {
    renderRows([reviewed("HCA", "review_unclear")]);
    const header = screen.getByRole("button", { name: "Analysis" }).closest("th") as HTMLElement;
    expect(header.className).not.toMatch(/\bw-|min-w-|max-w-/);
    expect(analysisCell("HCA").className).not.toMatch(/\bw-|min-w-|max-w-/);
    // the marker is a 12px icon plus a 4px gap
    const marker = analysisCell("HCA").querySelector("[data-testid='review-marker']") as HTMLElement;
    expect(marker).toHaveClass("ml-1");
    expect(marker.querySelector("svg")).toHaveAttribute("width", "12");
  });

  it("still sorts on overall_score only: a status moves nothing", () => {
    const rows = [reviewed("LOW", null, { overall_score: 60 }), reviewed("HI", "review_unclear", { overall_score: 90 }), reviewed("MID", "data_uncertain", { overall_score: 75 })];
    const sorted = sortWatchlistRows(rows, [{ field: "overall_score", direction: "desc" }]).map((r) => r.ticker);
    expect(sorted).toEqual(["HI", "MID", "LOW"]);
    renderRows(rows);
    const order = [...document.querySelectorAll("tbody tr")].map((tr) => tr.querySelector("td p")?.textContent);
    expect(order).toEqual(["HI", "MID", "LOW"]);
  });
});
