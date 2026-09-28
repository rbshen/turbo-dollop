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
