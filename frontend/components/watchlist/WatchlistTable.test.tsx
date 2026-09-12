// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WatchlistTable } from "@/components/watchlist/WatchlistTable";
import type { WatchlistOut, WatchlistRowOut } from "@/lib/api/types";
import { DEFAULT_SORT_RULES } from "@/lib/watchlistSort";

afterEach(cleanup);

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
    market_cap: 3_000_000_000_000,
    pe_ratio: 30,
    beta: 1.2,
    perf_5y_vs_spy_pct: null,
    perf_5y_vs_spy_status: null,
    speculative_growth_qualifies: false,
    consensus_rating: "Buy",
    added_at: "2026-01-01T00:00:00Z",
  },
];

describe("WatchlistTable sticky header", () => {
  it("keeps every column header cell sticky with a solid background", () => {
    render(
      <WatchlistTable watchlist={WATCHLIST} rows={ROWS} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={vi.fn()} />
    );
    for (const cell of document.querySelectorAll("thead th")) {
      expect(cell.className).toContain("sticky");
      expect(cell.className).toContain("top-12");
      expect(cell.className).toContain("bg-surface-2");
    }
  });

  it("still cycles sort rules when a sticky header is clicked", () => {
    const onSortRulesChange = vi.fn();
    render(
      <WatchlistTable watchlist={WATCHLIST} rows={ROWS} sortRules={DEFAULT_SORT_RULES} onSortRulesChange={onSortRulesChange} />
    );
    screen.getByRole("button", { name: "Moat" }).click();
    expect(onSortRulesChange).toHaveBeenCalledTimes(1);
  });
});
