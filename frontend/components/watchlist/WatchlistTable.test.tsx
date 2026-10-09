// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { overallCellTitle, WatchlistTable } from "@/components/watchlist/WatchlistTable";
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
    weinstein_stage: null,
    weinstein_stage_since_date: null,
    weinstein_stage_since_is_lower_bound: null,
    weinstein_ma_slope_pct: null,
    weinstein_vs_ma_pct: null,
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
  it("draws the verdict in its normal tone with the score and the note as its tooltip (scored as No moat)", () => {
    const unrated: WatchlistRowOut = { ...ROWS[0], ticker: "WSM", moat: null, overall_score: 56, overall_verdict: "Fail" };
    render(<WatchlistTable watchlist={WATCHLIST} rows={[ROWS[0], unrated]} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />);
    const cell = (ticker: string) => (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[8];
    const pill = cell("WSM").querySelector("span[title]") as HTMLElement;
    expect(pill).toHaveTextContent("May not pass");
    expect(pill).toHaveAttribute("title", "May not pass (overall score 56). Moat not rated, scored as No moat");
    expect(pill).toHaveClass("text-not-pass"); // a Fail, not a neutral "not rated" pill
    expect(cell("AAPL").querySelector("span[title]")).toHaveAttribute("title", "Pass (overall score 90)"); // a rated Pass: the word and the score
  });
});

describe("WatchlistTable: Pass with caution tooltip names its reason", () => {
  const caution = (overrides: Partial<WatchlistRowOut>): WatchlistRowOut => ({ ...ROWS[0], overall_verdict: "Pass with caution", overall_score: 80, ...overrides });

  it("names the weak step when a step is below the pass line", () => {
    expect(overallCellTitle(caution({ step4_score: 60, step4_verdict: "Fail" }))).toBe("Pass with caution (overall score 80). Because Profitability may not pass (under 70)");
  });

  it("names several weak steps, and a weak step is read from the score as well as a stored Fail", () => {
    expect(overallCellTitle(caution({ step1_score: 65, step1_verdict: "Fail", step5_score: 55, step5_verdict: "Fail" }))).toBe("Pass with caution (overall score 80). Because Financials and Debt may not pass (under 70)");
  });

  it("names both reasons when a Debt caution and a weak step apply together", () => {
    expect(overallCellTitle(caution({ step5_score: 74, step5_verdict: "Pass with caution", step2_score: 50, step2_verdict: "Fail" }))).toBe(
      "Pass with caution (overall score 80). Because Debt passed with a ratio in breach and Growth Rate may not pass (under 70)",
    );
  });

  it("joins three steps as 'A, B and C' in both parts of the tooltip", () => {
    expect(
      overallCellTitle(
        caution({
          step1_score: 60, step1_verdict: "Fail",
          step2_score: 50, step2_verdict: "Fail",
          step4_score: 55, step4_verdict: "Fail",
          step5_score: 74, step5_verdict: "Pass with caution",
        }),
      ),
    ).toBe("Pass with caution (overall score 80). Because Debt passed with a ratio in breach and Financials, Growth Rate and Profitability may not pass (under 70)");
  });

  it("keeps the Debt-only text for a step caution alone, and ignores a missing (exempt) score", () => {
    expect(overallCellTitle(caution({ step5_score: 74, step5_verdict: "Pass with caution" }))).toBe("Pass with caution (overall score 80). Because Debt passed with a ratio in breach");
    expect(overallCellTitle(caution({ step5_score: null, step5_verdict: "not_supported" }))).toBe("Pass with caution (overall score 80)");
  });

  it("is the verdict word and the score for a plain Pass or a Fail, and undefined with no score", () => {
    expect(overallCellTitle({ ...ROWS[0], step4_score: 60, step4_verdict: "Fail" })).toBe("Pass (overall score 90)");
    expect(overallCellTitle({ ...ROWS[0], overall_verdict: "Fail", overall_score: 50, step4_score: 60, step4_verdict: "Fail" })).toBe("May not pass (overall score 50)");
    expect(overallCellTitle({ ...ROWS[0], overall_verdict: null, overall_score: null })).toBeUndefined();
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

  function verdictCell(ticker: string) {
    const row = screen.getByText(ticker).closest("tr") as HTMLElement;
    return row.querySelectorAll("td")[8]; // Ticker, Sector, Last, Rev, NI, CFO, Moat, Value, Verdict
  }

  it("shows an ETF marker in the Verdict cell instead of the blank/missing verdict", () => {
    render(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={[ROWS[0], ETF_ROW]}
        sortRules={DEFAULT_SORT_RULES}
        onSortRulesChange={vi.fn()}
      />,
    );
    expect(verdictCell("QQQ")).toHaveTextContent("ETF");
    expect(verdictCell("QQQ")).not.toHaveTextContent("—");
    expect(verdictCell("AAPL")).toHaveTextContent("Pass"); // a stock row shows its verdict word, not the score
    expect(verdictCell("AAPL")).not.toHaveTextContent("90");
    expect(verdictCell("AAPL")).not.toHaveTextContent("ETF");
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
      (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[10]; // ... Verdict, Stage, Rating
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
    expect(verdictCell("QQQ")).toHaveTextContent("—");
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
    expect(ticker?.className).toContain("w-[110px]");
    expect(sector?.className).toContain("w-[100px]");
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

describe("WatchlistTable: Verdict cell", () => {
  const scored = (ticker: string, extra: Partial<WatchlistRowOut> = {}): WatchlistRowOut => ({
    ...ROWS[0],
    ticker,
    company_name: `${ticker} Corp`,
    overall_score: 71,
    overall_verdict: "Pass",
    ...extra,
  });
  const verdictCell = (ticker: string) =>
    (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[8] as HTMLElement;
  const renderRows = (rows: WatchlistRowOut[], sortRules = DEFAULT_SORT_RULES) =>
    render(<WatchlistTable watchlist={WATCHLIST} rows={rows} sortRules={sortRules} onSortRulesChange={vi.fn()} />);

  it("shows the verdict word alone, with the score in the tooltip; a Pass with caution has no glyph and names its reason", () => {
    renderRows([scored("HCA"), scored("GE", { overall_verdict: "Pass with caution", overall_score: 73, step5_verdict: "Pass with caution" })]);
    expect(verdictCell("HCA")).toHaveTextContent(/^Pass$/);
    expect(verdictCell("HCA").children).toHaveLength(1);
    expect(verdictCell("HCA").querySelector("span[title]")).toHaveAttribute("title", "Pass (overall score 71)");
    expect(verdictCell("GE")).toHaveTextContent(/^Pass with caution$/);
    expect(verdictCell("GE").textContent).not.toContain("⚠");
    expect(verdictCell("GE").querySelector("span[title]")).toHaveAttribute(
      "title",
      "Pass with caution (overall score 73). Because Debt passed with a ratio in breach",
    );
  });

  it("draws every stored verdict in its display word and tone", () => {
    renderRows([
      scored("SP", { overall_verdict: "Strong Pass", overall_score: 95 }),
      scored("FL", { overall_verdict: "Fail", overall_score: 55 }),
    ]);
    expect(verdictCell("SP")).toHaveTextContent("Strong pass");
    expect(verdictCell("SP").querySelector("span[title]")).toHaveClass("text-positive-strong");
    expect(verdictCell("FL")).toHaveTextContent("May not pass");
    expect(verdictCell("FL").querySelector("span[title]")).toHaveClass("text-not-pass");
  });

  it("shows the missing dash for an incomplete (null) verdict", () => {
    renderRows([scored("INC", { overall_verdict: null, overall_score: null })]);
    expect(verdictCell("INC")).toHaveTextContent("—");
  });

  it("an ETF row shows the ETF marker", () => {
    renderRows([scored("QQQ", { is_etf: true, overall_score: null, overall_verdict: null })]);
    expect(verdictCell("QQQ")).toHaveTextContent("ETF");
  });

  it("the Verdict header is a plain header: no button, no sort state, nothing sorted by it", () => {
    renderRows([scored("AAPL")]);
    expect(screen.queryByRole("button", { name: "Verdict" })).toBeNull();
    const head = screen.getByText("Verdict").closest("th") as HTMLElement;
    expect(head).not.toHaveAttribute("aria-sort");
    expect(head.querySelector("button, svg")).toBeNull();
    // The sortable neighbours keep their buttons.
    expect(screen.getByRole("button", { name: "Value" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rating" })).toBeInTheDocument();
  });

  it("the default sort is ticker A to Z, and the Ticker header shows it as ascending", () => {
    const rows = [scored("MSFT"), scored("AAPL"), scored("GOOG")];
    renderRows(rows);
    const order = [...document.querySelectorAll("tbody tr")].map((tr) => tr.querySelector("td p")?.textContent);
    expect(order).toEqual(["AAPL", "GOOG", "MSFT"]);
    expect(screen.getByRole("button", { name: "Ticker" }).closest("th")).toHaveAttribute("aria-sort", "ascending");
  });
});

describe("WatchlistTable: Stage column", () => {
  const withStage = (ticker: string, extra: Partial<WatchlistRowOut> = {}): WatchlistRowOut => ({ ...ROWS[0], ticker, company_name: `${ticker} Corp`, ...extra });
  const stageCell = (ticker: string) =>
    (screen.getByText(ticker).closest("tr") as HTMLElement).querySelectorAll("td")[9] as HTMLElement; // ... Verdict, Stage
  const renderRows = (rows: WatchlistRowOut[]) =>
    render(<WatchlistTable watchlist={WATCHLIST} rows={rows} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />);

  it("sits right after Verdict and is a plain header: no button, no sort state", () => {
    renderRows([withStage("AAPL")]);
    const headers = [...document.querySelectorAll("thead th")].map((h) => h.textContent?.trim());
    expect(headers.indexOf("Stage")).toBe(headers.indexOf("Verdict") + 1);
    expect(screen.queryByRole("button", { name: "Stage" })).toBeNull();
    const head = screen.getByText("Stage").closest("th") as HTMLElement;
    expect(head).not.toHaveAttribute("aria-sort");
    expect(head.querySelector("button, svg")).toBeNull();
  });

  it("draws the stage as the compact Weinstein pill with its full label and tooltip", () => {
    renderRows([
      withStage("AAPL", {
        weinstein_stage: "advance",
        weinstein_stage_since_date: "2026-03-02",
        weinstein_stage_since_is_lower_bound: false,
        weinstein_ma_slope_pct: 1.5,
        weinstein_vs_ma_pct: 8.2,
      }),
      withStage("DECL", { weinstein_stage: "decline" }),
    ]);
    expect(stageCell("AAPL")).toHaveTextContent(/^Stage 2 · Advance$/);
    const pill = stageCell("AAPL").querySelector("span[title]") as HTMLElement;
    expect(pill).toHaveClass("text-positive", "text-[11px]"); // advance is green; compact type size
    expect(pill.getAttribute("title")).toContain("slope: +1.5%");
    expect(stageCell("DECL")).toHaveTextContent("Stage 4 · Decline");
    expect(stageCell("DECL").querySelector("span[title]")).toHaveClass("text-negative");
  });

  it("shows the missing dash with one generic tooltip when there is no stage", () => {
    renderRows([withStage("NOST")]);
    expect(stageCell("NOST")).toHaveTextContent(/^—$/);
    expect(stageCell("NOST").querySelector("span[title]")).toHaveAttribute("title", "No Weinstein stage yet");
  });

  it("shows the stage of an ETF row in a stock list too, and the dash when it has none", () => {
    renderRows([withStage("QQQ", { is_etf: true, weinstein_stage: "top" }), withStage("SPY", { is_etf: true })]);
    expect(stageCell("QQQ")).toHaveTextContent("Stage 3 · Top");
    expect(stageCell("SPY")).toHaveTextContent("—");
  });
});

describe("WatchlistTable: Verdict truncation", () => {
  it("caps the pill width and ellipsises the word, with the full verdict in the title", () => {
    render(
      <WatchlistTable
        watchlist={WATCHLIST}
        rows={[{ ...ROWS[0], overall_verdict: "Pass with caution", overall_score: 73, step5_score: 74, step5_verdict: "Pass with caution" }]}
        sortRules={DEFAULT_SORT_RULES}
        onSortRulesChange={vi.fn()}
      />,
    );
    const cell = (screen.getByText("AAPL").closest("tr") as HTMLElement).querySelectorAll("td")[8] as HTMLElement;
    const pill = cell.querySelector("span[title]") as HTMLElement;
    expect(pill).toHaveClass("max-w-[96px]");
    const word = screen.getByText("Pass with caution");
    expect(word).toHaveClass("truncate");
    expect(pill).toContainElement(word);
    expect(pill.getAttribute("title")).toMatch(/^Pass with caution \(overall score 73\)/);
  });
});
