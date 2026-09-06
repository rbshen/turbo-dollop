import { describe, expect, it } from "vitest";

import type { WatchlistRowOut } from "@/lib/api/types";
import { applyHeaderClick, DEFAULT_SORT_RULES, MAX_SORT_RULES, parseSortRules, sortWatchlistRows, type SortRule } from "@/lib/watchlistSort";

function row(overrides: Partial<WatchlistRowOut> = {}): WatchlistRowOut {
  return {
    ticker: "AAPL",
    company_name: "Apple Inc.",
    sector: "Technology",
    exchange: "NASDAQ",
    years: [],
    revenue: [],
    net_income: [],
    cfo: [],
    moat: null,
    valuation_verdict: null,
    valuation_source: null,
    step1_score: null,
    step1_verdict: null,
    step2_score: null,
    step2_verdict: null,
    step4_score: null,
    step4_verdict: null,
    step5_score: null,
    step5_verdict: null,
    overall_score: null,
    overall_verdict: null,
    market_cap: null,
    pe_ratio: null,
    beta: null,
    perf_5y_vs_spy_pct: null,
    perf_5y_vs_spy_status: null,
    speculative_growth_qualifies: null,
    consensus_rating: "N/A",
    added_at: "2026-01-01T00:00:00",
    bar_level: null,
    blended_score: null,
    trend_state: null,
    ad_bullish_divergence: null,
    ad_divergence_swing_date: null,
    sma20_position_pct: null,
    sma20_cross: null,
    sma50_position_pct: null,
    sma50_cross: null,
    sma200_position_pct: null,
    sma200_cross: null,
    ...overrides,
  };
}

describe("sortWatchlistRows", () => {
  it("sorts by a single numeric rule", () => {
    const rows = [row({ ticker: "LOW", overall_score: 20 }), row({ ticker: "HIGH", overall_score: 90 })];
    const result = sortWatchlistRows(rows, [{ field: "overall_score", direction: "desc" }]);
    expect(result.map((r) => r.ticker)).toEqual(["HIGH", "LOW"]);
  });

  it("sorts nulls last regardless of direction", () => {
    const rows = [row({ ticker: "NULL", overall_score: null }), row({ ticker: "REAL", overall_score: 50 })];
    expect(sortWatchlistRows(rows, [{ field: "overall_score", direction: "asc" }]).map((r) => r.ticker)).toEqual(["REAL", "NULL"]);
    expect(sortWatchlistRows(rows, [{ field: "overall_score", direction: "desc" }]).map((r) => r.ticker)).toEqual(["REAL", "NULL"]);
  });

  it("sorts text fields via localeCompare", () => {
    const rows = [row({ ticker: "MSFT" }), row({ ticker: "AAPL" })];
    expect(sortWatchlistRows(rows, [{ field: "ticker", direction: "asc" }]).map((r) => r.ticker)).toEqual(["AAPL", "MSFT"]);
  });

  it("falls through to the second rule on a tie", () => {
    const rows = [
      row({ ticker: "B", overall_score: 80, market_cap: 100 }),
      row({ ticker: "A", overall_score: 80, market_cap: 200 }),
    ];
    const rules: SortRule[] = [
      { field: "overall_score", direction: "desc" },
      { field: "market_cap", direction: "desc" },
    ];
    expect(sortWatchlistRows(rows, rules).map((r) => r.ticker)).toEqual(["A", "B"]);
  });

  it("ranks Moat best-first ascending (Wide, then Narrow, then No Moat)", () => {
    const rows = [row({ ticker: "NO", moat: "no_moat" }), row({ ticker: "WIDE", moat: "wide_moat" }), row({ ticker: "NARROW", moat: "narrow_moat" })];
    const result = sortWatchlistRows(rows, [{ field: "moat", direction: "asc" }]);
    expect(result.map((r) => r.ticker)).toEqual(["WIDE", "NARROW", "NO"]);
  });

  it("sorts an unset Moat (null) last regardless of direction", () => {
    const rows = [row({ ticker: "UNSET", moat: null }), row({ ticker: "WIDE", moat: "wide_moat" })];
    expect(sortWatchlistRows(rows, [{ field: "moat", direction: "asc" }]).map((r) => r.ticker)).toEqual(["WIDE", "UNSET"]);
    expect(sortWatchlistRows(rows, [{ field: "moat", direction: "desc" }]).map((r) => r.ticker)).toEqual(["WIDE", "UNSET"]);
  });

  it("ranks Valuation best-first ascending (Undervalued, then Fair, then Overvalued)", () => {
    const rows = [
      row({ ticker: "OVER", valuation_verdict: "overvalued" }),
      row({ ticker: "UNDER", valuation_verdict: "undervalued" }),
      row({ ticker: "FAIR", valuation_verdict: "fair" }),
    ];
    const result = sortWatchlistRows(rows, [{ field: "valuation_verdict", direction: "asc" }]);
    expect(result.map((r) => r.ticker)).toEqual(["UNDER", "FAIR", "OVER"]);
  });

  it("ranks Rating best-first ascending across all 5 tiers, case-insensitively", () => {
    const rows = [
      row({ ticker: "SELL", consensus_rating: "Sell" }),
      row({ ticker: "STRONGBUY", consensus_rating: "Strong Buy" }),
      row({ ticker: "HOLD", consensus_rating: "Hold" }),
      row({ ticker: "STRONGSELL", consensus_rating: "Strong Sell" }),
      row({ ticker: "BUY", consensus_rating: "buy" }),
    ];
    const result = sortWatchlistRows(rows, [{ field: "consensus_rating", direction: "asc" }]);
    expect(result.map((r) => r.ticker)).toEqual(["STRONGBUY", "BUY", "HOLD", "SELL", "STRONGSELL"]);
  });

  it("sorts an unrecognized Rating string (e.g. the 'N/A' placeholder) last regardless of direction", () => {
    const rows = [row({ ticker: "NA", consensus_rating: "N/A" }), row({ ticker: "BUY", consensus_rating: "Buy" })];
    expect(sortWatchlistRows(rows, [{ field: "consensus_rating", direction: "asc" }]).map((r) => r.ticker)).toEqual(["BUY", "NA"]);
    expect(sortWatchlistRows(rows, [{ field: "consensus_rating", direction: "desc" }]).map((r) => r.ticker)).toEqual(["BUY", "NA"]);
  });

  it("sorts ad_divergence_swing_date as a null-last string proxy for the boolean flag", () => {
    const rows = [
      row({ ticker: "OLD", ad_bullish_divergence: true, ad_divergence_swing_date: "2026-01-01" }),
      row({ ticker: "NEW", ad_bullish_divergence: true, ad_divergence_swing_date: "2026-06-01" }),
      row({ ticker: "NONE", ad_bullish_divergence: null, ad_divergence_swing_date: null }),
    ];
    const result = sortWatchlistRows(rows, [{ field: "ad_divergence_swing_date", direction: "desc" }]);
    expect(result.map((r) => r.ticker)).toEqual(["NEW", "OLD", "NONE"]);
  });

  it("sorts Trend (blended_score) numerically, strongest uptrend first on desc, nulls last regardless of direction", () => {
    const rows = [
      row({ ticker: "WEAK", blended_score: -3.5 }),
      row({ ticker: "STRONG", blended_score: 8.2 }),
      row({ ticker: "NONE", blended_score: null }),
    ];
    expect(sortWatchlistRows(rows, [{ field: "blended_score", direction: "desc" }]).map((r) => r.ticker)).toEqual([
      "STRONG",
      "WEAK",
      "NONE",
    ]);
    expect(sortWatchlistRows(rows, [{ field: "blended_score", direction: "asc" }]).map((r) => r.ticker)).toEqual([
      "WEAK",
      "STRONG",
      "NONE",
    ]);
  });

  it("returns rows in their original/natural order (a no-op) when sortRules is empty", () => {
    // Deliberately NOT sorted by overall_score or anything else -- an
    // explicitly-cleared sortState must never fall back to an implicit
    // default order.
    const rows = [
      row({ ticker: "C", overall_score: 10 }),
      row({ ticker: "A", overall_score: 90 }),
      row({ ticker: "B", overall_score: 50 }),
    ];
    expect(sortWatchlistRows(rows, [])).toEqual(rows);
    expect(sortWatchlistRows(rows, []).map((r) => r.ticker)).toEqual(["C", "A", "B"]);
  });
});

describe("applyHeaderClick", () => {
  it("1st click appends a new field at its default direction", () => {
    const result = applyHeaderClick([], "ticker");
    expect(result).toEqual([{ field: "ticker", direction: "asc" }]);
  });

  it("appends as lowest priority behind existing rules", () => {
    const rules: SortRule[] = [{ field: "overall_score", direction: "desc" }];
    const result = applyHeaderClick(rules, "ticker");
    expect(result).toEqual([
      { field: "overall_score", direction: "desc" },
      { field: "ticker", direction: "asc" },
    ]);
  });

  it("2nd click flips direction in place without changing priority position", () => {
    const rules: SortRule[] = [
      { field: "market_cap", direction: "desc" },
      { field: "ticker", direction: "asc" },
    ];
    const result = applyHeaderClick(rules, "ticker");
    expect(result).toEqual([
      { field: "market_cap", direction: "desc" },
      { field: "ticker", direction: "desc" },
    ]);
  });

  it("3rd click (already flipped once) removes the field and shifts remaining priorities up", () => {
    const rules: SortRule[] = [
      { field: "ticker", direction: "desc" },
      { field: "market_cap", direction: "desc" },
    ];
    const result = applyHeaderClick(rules, "ticker");
    expect(result).toEqual([{ field: "market_cap", direction: "desc" }]);
  });

  it("allows sortState to become fully empty when the only active column is clicked a 3rd time", () => {
    // This is the regression this fix targets: removal used to fall back
    // to DEFAULT_SORT_RULES whenever it would leave the array empty, which
    // meant a 3rd click on the LAST remaining column silently did nothing
    // (you had to activate a second column first, remove that, then come
    // back for the first). Direct-to-empty must work from a length-1 start.
    const rules: SortRule[] = [{ field: "ticker", direction: "desc" }];
    const result = applyHeaderClick(rules, "ticker");
    expect(result).toEqual([]);
  });

  it("full click cycle on a single column, starting from and returning to empty sortState", () => {
    let rules: SortRule[] = [];
    rules = applyHeaderClick(rules, "market_cap"); // 1st click: append at default direction
    expect(rules).toEqual([{ field: "market_cap", direction: "desc" }]);
    rules = applyHeaderClick(rules, "market_cap"); // 2nd click: flip
    expect(rules).toEqual([{ field: "market_cap", direction: "asc" }]);
    rules = applyHeaderClick(rules, "market_cap"); // 3rd click: remove -- empty, not the default
    expect(rules).toEqual([]);
  });

  it("is a no-op when clicking a 5th, not-yet-active column while 4 are already active", () => {
    const rules: SortRule[] = [
      { field: "ticker", direction: "asc" },
      { field: "sector", direction: "asc" },
      { field: "market_cap", direction: "desc" },
      { field: "beta", direction: "desc" },
    ];
    expect(rules).toHaveLength(MAX_SORT_RULES);
    const result = applyHeaderClick(rules, "pe_ratio");
    expect(result).toBe(rules);
    expect(result).toHaveLength(MAX_SORT_RULES);
  });

  it("full click cycle for one column returns to append behavior after removal", () => {
    let rules = DEFAULT_SORT_RULES;
    rules = applyHeaderClick(rules, "ticker"); // 1st click: append
    expect(rules).toEqual([{ field: "overall_score", direction: "desc" }, { field: "ticker", direction: "asc" }]);
    rules = applyHeaderClick(rules, "ticker"); // 2nd click: flip
    expect(rules).toEqual([{ field: "overall_score", direction: "desc" }, { field: "ticker", direction: "desc" }]);
    rules = applyHeaderClick(rules, "ticker"); // 3rd click: remove
    expect(rules).toEqual([{ field: "overall_score", direction: "desc" }]);
    rules = applyHeaderClick(rules, "ticker"); // 4th click: append again, back at default direction
    expect(rules).toEqual([{ field: "overall_score", direction: "desc" }, { field: "ticker", direction: "asc" }]);
  });
});

describe("parseSortRules", () => {
  it("applies the overall_score-desc default when no key was ever persisted (a fresh watchlist)", () => {
    expect(parseSortRules(null)).toEqual(DEFAULT_SORT_RULES);
  });

  it("honors a persisted explicit empty array rather than falling back to the default", () => {
    expect(parseSortRules("[]")).toEqual([]);
  });

  it("round-trips a real persisted multi-rule value", () => {
    const rules: SortRule[] = [
      { field: "moat", direction: "asc" },
      { field: "market_cap", direction: "desc" },
    ];
    expect(parseSortRules(JSON.stringify(rules))).toEqual(rules);
  });

  it("falls back to the default on malformed JSON", () => {
    expect(parseSortRules("{not valid json")).toEqual(DEFAULT_SORT_RULES);
  });

  it("falls back to the default on a valid-JSON but non-SortRule[] shape", () => {
    expect(parseSortRules('"overall_score"')).toEqual(DEFAULT_SORT_RULES); // pre-redesign single-string shape
    expect(parseSortRules('[{"field": "not_a_real_field", "direction": "asc"}]')).toEqual(DEFAULT_SORT_RULES);
    expect(parseSortRules('[{"field": "ticker", "direction": "sideways"}]')).toEqual(DEFAULT_SORT_RULES);
  });

  it("falls back to the default when the persisted array exceeds MAX_SORT_RULES", () => {
    const tooMany: SortRule[] = [
      { field: "ticker", direction: "asc" },
      { field: "sector", direction: "asc" },
      { field: "market_cap", direction: "desc" },
      { field: "beta", direction: "desc" },
      { field: "pe_ratio", direction: "desc" },
    ];
    expect(parseSortRules(JSON.stringify(tooMany))).toEqual(DEFAULT_SORT_RULES);
  });
});
