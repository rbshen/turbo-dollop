import { describe, expect, it } from "vitest";

import type { TickerScoreOut } from "@/lib/api/types";
import { checkNumber } from "@/lib/numberInput";
import {
  DEFAULT_FILTER_STATE,
  FUNDAMENTAL_FILTER_KEYS,
  MOAT_FILTER_OPTIONS,
  OVERALL_INCOMPLETE,
  OVERALL_VERDICT_FILTER_OPTIONS,
  TECHNICAL_FILTER_KEYS,
  WARREN_SIGNAL_KIND_FILTER_OPTIONS,
  countActiveFilters,
  excludeEtfs,
  extractCompanyTypes,
  extractSectors,
  filterTickerScores,
  MARKET_CAP_SUFFIXES,
  formatMarketCapInput,
  isEtfRow,
  sortTickerScores,
  type ScreenerFilterState,
} from "@/lib/screenerFilters";

function row(overrides: Partial<TickerScoreOut> = {}): TickerScoreOut {
  return {
    ticker: "AAPL",
    company_name: "Apple Inc.",
    sector: "Technology",
    industry: "Consumer Electronics",
    company_type: "Standard",
    is_etf: false,
    step1_score: 90,
    step1_verdict: "Strong Pass",
    step2_score: 80,
    step2_verdict: "Pass",
    step4_score: 70,
    step4_verdict: "Pass",
    step5_score: 60,
    step5_verdict: "Pass",
    moat: null,
    steps_score: null,
    moat_multiplier: null,
    overall_score: 78,
    overall_verdict: "Pass",
    market_cap: 3_000_000_000_000,
    last_price: 190,
    quote_currency: "USD",
    reported_currency: "USD",
    pe_ratio: 30,
    beta: 1.2,
    valuation_verdict: null,
    valuation_source: null,
    growth_rate: 12.5,
    computed_at: "2026-01-01T00:00:00",
    perf_5y_vs_spy_pct: null,
    perf_5y_vs_spy_status: null,
    speculative_growth_qualifies: null,
    weinstein_stage: null,
    weinstein_stage_since_date: null,
    weinstein_stage_since_is_lower_bound: null,
    weinstein_ma_slope_pct: null,
    weinstein_vs_ma_pct: null,
    weinstein_pending_direction: null,
    bb_rsi_entry_signal: null,
    warren_active_signal_kind: null,
    warren_last_buy_fired_at: null,
    ...overrides,
  };
}

describe("filterTickerScores", () => {
  it("returns everything unfiltered when every field is at its default (no-op)", () => {
    const rows = [row({ ticker: "AAPL" }), row({ ticker: "MSFT" })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(2);
  });

  it("does not filter by watchlist membership when watchlistTickers is null (default)", () => {
    const rows = [row({ ticker: "AAPL" }), row({ ticker: "MSFT" })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(2);
  });

  it("narrows to watchlist membership when a watchlistTickers set is passed", () => {
    const rows = [row({ ticker: "AAPL" }), row({ ticker: "MSFT" }), row({ ticker: "GOOG" })];
    const result = filterTickerScores(rows, DEFAULT_FILTER_STATE, new Set(["MSFT", "GOOG"]));
    expect(result.map((r) => r.ticker)).toEqual(["MSFT", "GOOG"]);
  });

  it("combines watchlist membership with an ordinary field filter, both must pass", () => {
    const rows = [
      row({ ticker: "IN_LIST_HIGH", overall_score: 90, overall_verdict: "Pass" }),
      row({ ticker: "IN_LIST_LOW", overall_score: 20, overall_verdict: "Fail" }),
      row({ ticker: "NOT_IN_LIST", overall_score: 90, overall_verdict: "Pass" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Pass"] };
    const result = filterTickerScores(rows, filters, new Set(["IN_LIST_HIGH", "IN_LIST_LOW"]));
    expect(result.map((r) => r.ticker)).toEqual(["IN_LIST_HIGH"]);
  });

  it("does not exclude an Incomplete ticker when no filter is active on its missing field", () => {
    const rows = [row({ ticker: "INCOMPLETE", overall_score: null, overall_verdict: null })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(1);
  });

  it("filters by a min/max range together", () => {
    const rows = [row({ ticker: "A", pe_ratio: 5 }), row({ ticker: "B", pe_ratio: 20 }), row({ ticker: "C", pe_ratio: 50 })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, peRatio: { min: 10, max: 30 } };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["B"]);
  });

  it("filters by Quote range, excluding a null last_price rather than treating it as 0", () => {
    const rows = [
      row({ ticker: "CHEAP", last_price: 5 }),
      row({ ticker: "MID", last_price: 100 }),
      row({ ticker: "NO_PRICE", last_price: null }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, quote: { min: 50, max: 200 } };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["MID"]);
  });

  it("filters by sector multi-select", () => {
    const rows = [
      row({ ticker: "TECH", sector: "Technology" }),
      row({ ticker: "FIN", sector: "Financial Services" }),
      row({ ticker: "HEALTH", sector: "Healthcare" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, sectors: ["Technology", "Healthcare"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["TECH", "HEALTH"]);
  });

  it("filters by company type multi-select", () => {
    const rows = [
      row({ ticker: "BANK1", company_type: "Bank" }),
      row({ ticker: "STD1", company_type: "Standard" }),
      row({ ticker: "BANK2", company_type: "Bank" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, companyTypes: ["Bank"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["BANK1", "BANK2"]);
  });

  it("combines a score filter and a company type filter (AND, not OR)", () => {
    const rows = [
      row({ ticker: "BANK_HIGH", company_type: "Bank", step5_score: 90 }),
      row({ ticker: "BANK_LOW", company_type: "Bank", step5_score: 10 }),
      row({ ticker: "STD_HIGH", company_type: "Standard", step5_score: 90 }),
    ];
    const filters: ScreenerFilterState = {
      ...DEFAULT_FILTER_STATE,
      companyTypes: ["Bank"],
      step5Score: { min: 70, max: null },
    };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["BANK_HIGH"]);
  });

  it("excludes a ticker missing sector entirely once a sector filter is active", () => {
    const rows = [row({ ticker: "NOSECTOR", sector: null })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, sectors: ["Technology"] };
    expect(filterTickerScores(rows, filters)).toHaveLength(0);
  });

  it("filters by moat multi-select", () => {
    const rows = [
      row({ ticker: "WIDE", moat: "wide_moat" }),
      row({ ticker: "NARROW", moat: "narrow_moat" }),
      row({ ticker: "NONE", moat: "no_moat" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, moat: ["wide_moat", "no_moat"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["WIDE", "NONE"]);
  });

  it('treats a null moat as the "not_set" filter value', () => {
    const rows = [row({ ticker: "UNSET", moat: null }), row({ ticker: "WIDE", moat: "wide_moat" })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, moat: ["not_set"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["UNSET"]);
  });

  it("does not exclude a null-moat ticker when no moat filter is active", () => {
    const rows = [row({ ticker: "UNSET", moat: null })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(1);
  });

  it("filters by valuation status multi-select", () => {
    const rows = [
      row({ ticker: "UNDER", valuation_verdict: "undervalued" }),
      row({ ticker: "OVER", valuation_verdict: "overvalued" }),
      row({ ticker: "FAIR", valuation_verdict: "fair" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, valuationVerdict: ["undervalued", "overvalued"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["UNDER", "OVER"]);
  });

  it("excludes a ticker missing a valuation verdict once a valuation filter is active", () => {
    const rows = [row({ ticker: "NOVERDICT", valuation_verdict: null })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, valuationVerdict: ["undervalued"] };
    expect(filterTickerScores(rows, filters)).toHaveLength(0);
  });

  it("filters by a growth rate range", () => {
    const rows = [row({ ticker: "FAST", growth_rate: 25 }), row({ ticker: "SLOW", growth_rate: 2 })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, growthRate: { min: 10, max: null } };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["FAST"]);
  });

  it("excludes a ticker missing a growth rate once a growth rate filter is active", () => {
    const rows = [row({ ticker: "NOGROWTH", growth_rate: null })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, growthRate: { min: 10, max: null } };
    expect(filterTickerScores(rows, filters)).toHaveLength(0);
  });

  it("filters by vs-SPY status multi-select", () => {
    const rows = [
      row({ ticker: "BEATS", perf_5y_vs_spy_status: "outperform" }),
      row({ ticker: "LAGS", perf_5y_vs_spy_status: "underperform" }),
      row({ ticker: "UNKNOWN", perf_5y_vs_spy_status: "no_data" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, vsSpy: ["outperform"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["BEATS"]);
  });

  it('filters by vs-SPY "match" status', () => {
    const rows = [
      row({ ticker: "TIED", perf_5y_vs_spy_status: "match" }),
      row({ ticker: "BEATS", perf_5y_vs_spy_status: "outperform" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, vsSpy: ["match"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["TIED"]);
  });

  it('treats a null vs-SPY status as the "no_data" filter value', () => {
    // A TickerScore row computed before this field existed (see
    // _add_missing_columns) reads null, same bucket as a genuine no_data.
    const rows = [row({ ticker: "PREDATES_FIELD", perf_5y_vs_spy_status: null }), row({ ticker: "BEATS", perf_5y_vs_spy_status: "outperform" })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, vsSpy: ["no_data"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["PREDATES_FIELD"]);
  });

  it("does not exclude a null vs-SPY ticker when no vs-SPY filter is active", () => {
    const rows = [row({ ticker: "PREDATES_FIELD", perf_5y_vs_spy_status: null })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(1);
  });

  it("filters by Weinstein stage multi-select", () => {
    const rows = [
      row({ ticker: "ADV", weinstein_stage: "advance" }),
      row({ ticker: "DEC", weinstein_stage: "decline" }),
      row({ ticker: "BASE", weinstein_stage: "base" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, weinsteinStages: ["advance", "base"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["ADV", "BASE"]);
  });

  it("Pending matches any Flip-ETA ticker regardless of stage, OR-combined with stages", () => {
    const rows = [
      row({ ticker: "ADV", weinstein_stage: "advance" }),
      row({ ticker: "PEND_ADV", weinstein_stage: "top", weinstein_pending_direction: "decline" }),
      row({ ticker: "PEND_NOSTAGE", weinstein_stage: null, weinstein_pending_direction: "advance" }),
      row({ ticker: "PLAIN", weinstein_stage: "base" }),
    ];
    const pendingOnly: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, weinsteinStages: ["pending"] };
    expect(filterTickerScores(rows, pendingOnly).map((r) => r.ticker)).toEqual(["PEND_ADV", "PEND_NOSTAGE"]);
    const both: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, weinsteinStages: ["advance", "pending"] };
    expect(filterTickerScores(rows, both).map((r) => r.ticker)).toEqual(["ADV", "PEND_ADV", "PEND_NOSTAGE"]);
  });

  it("excludes a ticker with no Weinstein stage once the filter is active", () => {
    const rows = [row({ ticker: "PREDATES_FIELD", weinstein_stage: null })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, weinsteinStages: ["advance"] };
    expect(filterTickerScores(rows, filters)).toHaveLength(0);
  });

  it("does not exclude a null-Weinstein-stage ticker when no Weinstein filter is active", () => {
    const rows = [row({ ticker: "PREDATES_FIELD", weinstein_stage: null })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(1);
  });

  it("does not filter by Speculative Growth when the checkbox is unchecked (default)", () => {
    const rows = [
      row({ ticker: "QUALIFIES", speculative_growth_qualifies: true }),
      row({ ticker: "DOES_NOT", speculative_growth_qualifies: false }),
      row({ ticker: "PREDATES_FIELD", speculative_growth_qualifies: null }),
    ];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(3);
  });

  it("shows only qualifies=true tickers when the Speculative Growth checkbox is checked", () => {
    const rows = [
      row({ ticker: "QUALIFIES", speculative_growth_qualifies: true }),
      row({ ticker: "DOES_NOT", speculative_growth_qualifies: false }),
      row({ ticker: "PREDATES_FIELD", speculative_growth_qualifies: null }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, speculativeGrowth: true };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["QUALIFIES"]);
  });

  it("filters by Warren signal kind multi-select (OR semantics across selected kinds)", () => {
    const rows = [
      row({ ticker: "BLUE", warren_active_signal_kind: "blue_up" }),
      row({ ticker: "YELLOW", warren_active_signal_kind: "yellow_up" }),
      row({ ticker: "GRAY", warren_active_signal_kind: "gray_up" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, warrenSignalKinds: ["blue_up", "gray_up"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["BLUE", "GRAY"]);
  });

  it("excludes a ticker with no active Warren signal once the filter is active", () => {
    const rows = [row({ ticker: "PREDATES_FIELD", warren_active_signal_kind: null })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, warrenSignalKinds: ["blue_up"] };
    expect(filterTickerScores(rows, filters)).toHaveLength(0);
  });

  it("does not exclude a null-Warren-signal ticker when no Warren filter is active", () => {
    const rows = [row({ ticker: "PREDATES_FIELD", warren_active_signal_kind: null })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(1);
  });
});

describe("sortTickerScores", () => {
  it("sorts ascending by a score field", () => {
    const rows = [row({ ticker: "B", step5_score: 50 }), row({ ticker: "A", step5_score: 10 }), row({ ticker: "C", step5_score: 90 })];
    expect(sortTickerScores(rows, "step5_score", "asc").map((r) => r.ticker)).toEqual(["A", "B", "C"]);
  });

  it("sorts descending by a score field", () => {
    const rows = [row({ ticker: "B", step5_score: 50 }), row({ ticker: "A", step5_score: 10 }), row({ ticker: "C", step5_score: 90 })];
    expect(sortTickerScores(rows, "step5_score", "desc").map((r) => r.ticker)).toEqual(["C", "B", "A"]);
  });

  it("sorts nulls to the end regardless of direction (ascending)", () => {
    const rows = [
      row({ ticker: "MID", step5_score: 50 }),
      row({ ticker: "NULL", step5_score: null }),
      row({ ticker: "LOW", step5_score: 10 }),
    ];
    expect(sortTickerScores(rows, "step5_score", "asc").map((r) => r.ticker)).toEqual(["LOW", "MID", "NULL"]);
  });

  it("sorts nulls to the end regardless of direction (descending)", () => {
    const rows = [
      row({ ticker: "MID", step5_score: 50 }),
      row({ ticker: "NULL", step5_score: null }),
      row({ ticker: "LOW", step5_score: 10 }),
    ];
    expect(sortTickerScores(rows, "step5_score", "desc").map((r) => r.ticker)).toEqual(["MID", "LOW", "NULL"]);
  });

  it("sorts by warren_signal_recency, most recent first on desc", () => {
    const rows = [
      row({ ticker: "OLD", warren_last_buy_fired_at: "2026-01-01T00:00:00" }),
      row({ ticker: "RECENT", warren_last_buy_fired_at: "2026-09-01T00:00:00" }),
      row({ ticker: "MID", warren_last_buy_fired_at: "2026-05-01T00:00:00" }),
    ];
    expect(sortTickerScores(rows, "warren_signal_recency", "desc").map((r) => r.ticker)).toEqual(["RECENT", "MID", "OLD"]);
  });

  it("sorts tickers with no Warren signal history to the end regardless of direction", () => {
    const rows = [
      row({ ticker: "HAS_SIGNAL", warren_last_buy_fired_at: "2026-05-01T00:00:00" }),
      row({ ticker: "NO_SIGNAL", warren_last_buy_fired_at: null }),
    ];
    expect(sortTickerScores(rows, "warren_signal_recency", "asc").map((r) => r.ticker)).toEqual(["HAS_SIGNAL", "NO_SIGNAL"]);
    expect(sortTickerScores(rows, "warren_signal_recency", "desc").map((r) => r.ticker)).toEqual(["HAS_SIGNAL", "NO_SIGNAL"]);
  });

  it("sorts by weinstein_stage_since, freshest flip first on desc, nulls last either way", () => {
    const rows = [
      row({ ticker: "OLD", weinstein_stage_since_date: "2025-01-06" }),
      row({ ticker: "NONE", weinstein_stage_since_date: null }),
      row({ ticker: "FRESH", weinstein_stage_since_date: "2026-09-14" }),
      row({ ticker: "MID", weinstein_stage_since_date: "2026-03-02" }),
    ];
    expect(sortTickerScores(rows, "weinstein_stage_since", "desc").map((r) => r.ticker)).toEqual(["FRESH", "MID", "OLD", "NONE"]);
    expect(sortTickerScores(rows, "weinstein_stage_since", "asc").map((r) => r.ticker)).toEqual(["OLD", "MID", "FRESH", "NONE"]);
  });

  it("does not mutate the input array", () => {
    const rows = [row({ ticker: "B", step5_score: 50 }), row({ ticker: "A", step5_score: 10 })];
    const original = [...rows];
    sortTickerScores(rows, "step5_score", "asc");
    expect(rows).toEqual(original);
  });

  it("sorts by a raw metric field (market cap)", () => {
    const rows = [
      row({ ticker: "SMALL", market_cap: 1_000_000_000 }),
      row({ ticker: "BIG", market_cap: 3_000_000_000_000 }),
    ];
    expect(sortTickerScores(rows, "market_cap", "desc").map((r) => r.ticker)).toEqual(["BIG", "SMALL"]);
  });

  it("sorts by Quote (last_price), nulls last", () => {
    const rows = [
      row({ ticker: "NO_PRICE", last_price: null }),
      row({ ticker: "CHEAP", last_price: 5 }),
      row({ ticker: "EXPENSIVE", last_price: 500 }),
    ];
    expect(sortTickerScores(rows, "last_price", "desc").map((r) => r.ticker)).toEqual(["EXPENSIVE", "CHEAP", "NO_PRICE"]);
    expect(sortTickerScores(rows, "last_price", "asc").map((r) => r.ticker)).toEqual(["CHEAP", "EXPENSIVE", "NO_PRICE"]);
  });

  it("sorts by growth rate", () => {
    const rows = [row({ ticker: "SLOW", growth_rate: 2 }), row({ ticker: "FAST", growth_rate: 25 })];
    expect(sortTickerScores(rows, "growth_rate", "desc").map((r) => r.ticker)).toEqual(["FAST", "SLOW"]);
  });
});

// The old strict parseMarketCapInput is gone; a market-cap box is parsed by the
// shared checkNumber with the market-cap suffixes and a minimum of 0 (exactly
// what RangeField passes). These are the old parser's cases moved onto that path.
const capText = (text: string) => checkNumber(text, { optional: true, suffixes: MARKET_CAP_SUFFIXES, min: 0 });

describe("market-cap text (checkNumber with MARKET_CAP_SUFFIXES)", () => {
  it("parses a bare number as raw dollars", () => {
    expect(capText("3000000000")).toEqual({ value: 3_000_000_000, error: null });
  });

  it("parses empty as null (no filter on that side), with no error", () => {
    expect(capText("")).toEqual({ value: null, error: null });
    expect(capText("   ")).toEqual({ value: null, error: null });
  });

  it.each([
    ["1B", 1_000_000_000],
    ["1 B", 1_000_000_000],
    ["1b", 1_000_000_000],
    ["1 b", 1_000_000_000],
    ["2M", 2_000_000],
    ["2 m", 2_000_000],
    ["1.5B", 1_500_000_000],
    ["1T", 1_000_000_000_000],
    ["5 t", 5_000_000_000_000],
    ["2.5T", 2_500_000_000_000],
    ["12.", 12],
    [".5", 0.5],
    [".5B", 500_000_000],
  ])("parses %s -> %d", (input, expected) => {
    expect(capText(input)).toEqual({ value: expected, error: null });
  });

  it.each([["1X"], ["1BX"], ["1 gazillion"], ["abc"], ["1BB"], ["5e"], ["1x"]])("%s is invalid text", (input) => {
    expect(capText(input).error).not.toBeNull();
  });

  it.each([["-5B"], ["-5"]])("%s is below the minimum of 0", (input) => {
    expect(capText(input).error).not.toBeNull();
  });
});

describe("formatMarketCapInput", () => {
  it("shows the shortest exact form", () => {
    expect(formatMarketCapInput(1e9)).toBe("1B");
    expect(formatMarketCapInput(5e12)).toBe("5T");
    expect(formatMarketCapInput(1.5e9)).toBe("1.5B");
    expect(formatMarketCapInput(2.5e12)).toBe("2.5T");
  });

  it("falls back to plain digits, and to empty for null", () => {
    expect(formatMarketCapInput(1_234_567)).toBe("1234567");
    expect(formatMarketCapInput(750_000)).toBe("750000");
    expect(formatMarketCapInput(null)).toBe("");
  });

  it("round-trips through the parser too", () => {
    for (const value of [1e9, 1.5e9, 5e12, 2.5e12, 3e6, 1_234_567]) {
      expect(capText(formatMarketCapInput(value)).value).toBe(value);
    }
  });
});

describe("countActiveFilters", () => {
  it("is 0 for the default state and 0 with no watchlist in effect", () => {
    expect(countActiveFilters(DEFAULT_FILTER_STATE, false)).toBe(0);
  });

  it("counts a range once, whether min, max or both are set", () => {
    expect(countActiveFilters({ ...DEFAULT_FILTER_STATE, quote: { min: 10, max: null } }, false)).toBe(1);
    expect(countActiveFilters({ ...DEFAULT_FILTER_STATE, quote: { min: null, max: 0 } }, false)).toBe(1);
    expect(countActiveFilters({ ...DEFAULT_FILTER_STATE, quote: { min: 1, max: 2 } }, false)).toBe(1);
  });

  it("counts each non-empty multi-select once, however many options are chosen", () => {
    const state = { ...DEFAULT_FILTER_STATE, sectors: ["Technology", "Energy"], moat: ["wide_moat"] };
    expect(countActiveFilters(state, false)).toBe(2);
  });

  it("counts checked chips", () => {
    const state = { ...DEFAULT_FILTER_STATE, speculativeGrowth: true, bbRsiEntrySignal: true };
    expect(countActiveFilters(state, false)).toBe(2);
  });

  it("counts a watchlist only when it is actually in effect", () => {
    expect(countActiveFilters(DEFAULT_FILTER_STATE, true)).toBe(1);
    expect(countActiveFilters(DEFAULT_FILTER_STATE, false)).toBe(0);
  });

  it("adds everything together", () => {
    const state = {
      ...DEFAULT_FILTER_STATE,
      overallVerdicts: ["Strong Pass", "Pass"],
      marketCap: { min: 1e9, max: 5e12 },
      sectors: ["Technology"],
      speculativeGrowth: true,
    };
    expect(countActiveFilters(state, true)).toBe(5);
  });
});

describe("extractSectors / extractCompanyTypes", () => {
  it("extracts unique, sorted, non-null sector values", () => {
    const rows = [row({ sector: "Technology" }), row({ sector: "Healthcare" }), row({ sector: "Technology" }), row({ sector: null })];
    expect(extractSectors(rows)).toEqual(["Healthcare", "Technology"]);
  });

  it("extracts unique, sorted, non-null company type values", () => {
    const rows = [row({ company_type: "Bank" }), row({ company_type: "Standard" }), row({ company_type: "Bank" })];
    expect(extractCompanyTypes(rows)).toEqual(["Bank", "Standard"]);
  });
});

describe("excludeEtfs", () => {
  it("drops rows flagged is_etf=true and keeps stocks", () => {
    const rows = [
      row({ ticker: "AAPL", is_etf: false }),
      row({ ticker: "QQQ", is_etf: true, company_type: "ETF" }),
      row({ ticker: "ARKK", is_etf: true, company_type: "ETF" }),
    ];
    expect(excludeEtfs(rows).map((r) => r.ticker)).toEqual(["AAPL"]);
  });

  it("trusts an explicit is_etf=false over company_type", () => {
    // is_etf is derived from the profile flag directly; it wins whenever it's set.
    expect(isEtfRow(row({ is_etf: false, company_type: "ETF" }))).toBe(false);
  });

  it("falls back to company_type === ETF for a row with no is_etf yet (pre-recompute)", () => {
    const rows = [
      row({ ticker: "SPY", is_etf: null, company_type: "ETF" }),
      row({ ticker: "AAPL", is_etf: null, company_type: "Standard" }),
    ];
    expect(excludeEtfs(rows).map((r) => r.ticker)).toEqual(["AAPL"]);
  });

  it("keeps a legacy row with neither is_etf nor company_type (not silently dropped)", () => {
    expect(isEtfRow(row({ is_etf: null, company_type: null }))).toBe(false);
  });

  it("makes ETFs invisible to the filters and to the Company type options", () => {
    const rows = excludeEtfs([
      row({ ticker: "AAPL" }),
      row({ ticker: "SPY", is_etf: true, company_type: "ETF" }),
    ]);
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE).map((r) => r.ticker)).toEqual(["AAPL"]);
    expect(extractCompanyTypes(rows)).toEqual(["Standard"]);
  });
});

// Characterization (Screener migration, session 1): pins today's behaviour of
// every range filter -- inclusive bounds, a null value never passes an active
// range, an inactive side is open, and a reversed range (min above max) applies
// literally so nothing matches -- so the sidebar migration cannot change it.
const RANGE_FILTERS: { key: keyof ScreenerFilterState; field: keyof TickerScoreOut }[] = [
  { key: "step1Score", field: "step1_score" },
  { key: "step2Score", field: "step2_score" },
  { key: "step4Score", field: "step4_score" },
  { key: "step5Score", field: "step5_score" },
  { key: "quote", field: "last_price" },
  { key: "marketCap", field: "market_cap" },
  { key: "peRatio", field: "pe_ratio" },
  { key: "beta", field: "beta" },
  { key: "growthRate", field: "growth_rate" },
];

describe.each(RANGE_FILTERS)("range filter $key (reads $field)", ({ key, field }) => {
  const rows = [
    row({ ticker: "LOW", [field]: 10 }),
    row({ ticker: "MID", [field]: 50 }),
    row({ ticker: "HIGH", [field]: 90 }),
    row({ ticker: "NULL", [field]: null }),
  ];
  const run = (range: { min: number | null; max: number | null }) =>
    filterTickerScores(rows, { ...DEFAULT_FILTER_STATE, [key]: range }).map((r) => r.ticker);

  it("min only: keeps values at or above it (inclusive), drops a null", () => {
    expect(run({ min: 50, max: null })).toEqual(["MID", "HIGH"]);
  });

  it("max only: keeps values at or below it (inclusive), drops a null", () => {
    expect(run({ min: null, max: 50 })).toEqual(["LOW", "MID"]);
  });

  it("min and max together, both inclusive", () => {
    expect(run({ min: 10, max: 50 })).toEqual(["LOW", "MID"]);
    expect(run({ min: 50, max: 50 })).toEqual(["MID"]);
  });

  it("an empty range is no filter at all, so a null still passes", () => {
    expect(run({ min: null, max: null })).toEqual(["LOW", "MID", "HIGH", "NULL"]);
  });

  it("a reversed range (min above max) applies literally: nothing matches", () => {
    expect(run({ min: 90, max: 10 })).toEqual([]);
  });

  it("zero and negative bounds are real bounds, not 'unset'", () => {
    expect(run({ min: 0, max: null })).toEqual(["LOW", "MID", "HIGH"]);
    expect(run({ min: null, max: 0 })).toEqual([]);
    expect(run({ min: -5, max: null })).toEqual(["LOW", "MID", "HIGH"]);
  });
});

describe("saved-view shallow merge onto the defaults", () => {
  // Same expression the Screener page uses on load: { ...DEFAULT_FILTER_STATE, ...saved.filters }.
  const merge = (saved: unknown) => ({ ...DEFAULT_FILTER_STATE, ...(saved as Partial<ScreenerFilterState>) });

  it("a view saved before newer keys existed loads with those keys at their defaults", () => {
    const old = { overallVerdicts: ["Pass"], sectors: ["Technology"] };
    const merged = merge(old);
    expect(merged.overallVerdicts).toEqual(["Pass"]);
    expect(merged.beta).toEqual({ min: null, max: null });
    expect(merged.vsSpy).toEqual([]);
    expect(merged.speculativeGrowth).toBe(false);
    expect(merged.bbRsiEntrySignal).toBe(false);
    expect(merged.warrenSignalKinds).toEqual([]);
    expect(filterTickerScores([row({ ticker: "A", overall_verdict: "Pass" })], merged)).toHaveLength(1);
  });

  it("a view carrying the removed 'country' key still filters cleanly (the key is ignored)", () => {
    const stale = { ...DEFAULT_FILTER_STATE, country: ["US"], overallVerdicts: ["Pass"] };
    const merged = merge(stale);
    const result = filterTickerScores([row({ ticker: "A", overall_verdict: "Pass" }), row({ ticker: "B", overall_verdict: "Fail" })], merged);
    expect(result.map((r) => r.ticker)).toEqual(["A"]);
  });
});

describe("countActiveFilters per section", () => {
  it("Fundamental and Technical together are exactly every filter in the state, with no overlap", () => {
    const all = Object.keys(DEFAULT_FILTER_STATE).sort();
    const sections = [...FUNDAMENTAL_FILTER_KEYS, ...TECHNICAL_FILTER_KEYS];
    expect([...sections].sort()).toEqual(all);
    expect(new Set(sections).size).toBe(sections.length);
  });

  it("counts only the section's own keys", () => {
    const state: ScreenerFilterState = {
      ...DEFAULT_FILTER_STATE,
      overallVerdicts: ["Pass"],
      sectors: ["Energy"],
      beta: { min: null, max: 2 },
      bbRsiEntrySignal: true,
    };
    expect(countActiveFilters(state, false, FUNDAMENTAL_FILTER_KEYS)).toBe(2);
    expect(countActiveFilters(state, false, TECHNICAL_FILTER_KEYS)).toBe(2);
    expect(countActiveFilters(state, false)).toBe(4);
  });

  it("adds the watchlist only when it is in effect, and counts it with no keys at all", () => {
    expect(countActiveFilters(DEFAULT_FILTER_STATE, true, [])).toBe(1);
    expect(countActiveFilters(DEFAULT_FILTER_STATE, false, [])).toBe(0);
    expect(countActiveFilters({ ...DEFAULT_FILTER_STATE, quote: { min: 1, max: null } }, true, [])).toBe(1);
  });

  it("never counts a key the state does not have (a stale saved-view key such as country)", () => {
    const stale = { ...DEFAULT_FILTER_STATE, country: ["US"] } as ScreenerFilterState;
    expect(countActiveFilters(stale, false)).toBe(0);
  });
});

describe("sentence-case option labels (display only)", () => {
  it("re-cases the Moat and Warren labels but keeps every stored value", () => {
    expect(MOAT_FILTER_OPTIONS).toEqual([
      { value: "wide_moat", label: "Wide moat" },
      { value: "narrow_moat", label: "Narrow moat" },
      { value: "no_moat", label: "No moat" },
      { value: "not_set", label: "Not set" },
    ]);
    expect(WARREN_SIGNAL_KIND_FILTER_OPTIONS).toEqual([
      { value: "blue_up", label: "Blue up" },
      { value: "yellow_up", label: "Yellow up" },
      { value: "gray_up", label: "Gray up" },
    ]);
  });
});

describe("a saved view that still carries the retired reviewStatuses key", () => {
  it("merges onto the defaults without error, filters nothing and adds nothing to the active count", () => {
    const merged = { ...DEFAULT_FILTER_STATE, ...({ reviewStatuses: ["review_unclear"], moat: ["wide_moat"] } as unknown as Partial<ScreenerFilterState>) };
    expect(filterTickerScores([row({ ticker: "A", moat: "wide_moat" }), row({ ticker: "B", moat: "wide_moat" })], merged).map((r) => r.ticker)).toEqual(["A", "B"]);
    expect(countActiveFilters(merged, false)).toBe(1);
    expect("reviewStatuses" in DEFAULT_FILTER_STATE).toBe(false);
  });
});

describe("Overall verdict filter", () => {
  const rows = [
    row({ ticker: "SP", overall_score: 95, overall_verdict: "Strong Pass" }),
    row({ ticker: "P", overall_score: 80, overall_verdict: "Pass" }),
    row({ ticker: "PWC", overall_score: 74, overall_verdict: "Pass with caution" }),
    row({ ticker: "FAIL", overall_score: 55, overall_verdict: "Fail" }),
    row({ ticker: "INC", overall_score: null, overall_verdict: null }),
  ];
  const run = (overallVerdicts: string[], extra: Partial<ScreenerFilterState> = {}) =>
    filterTickerScores(rows, { ...DEFAULT_FILTER_STATE, overallVerdicts, ...extra }).map((r) => r.ticker);

  it("offers the five options with the raw stored keys, Fail drawn as May not pass", () => {
    expect(OVERALL_VERDICT_FILTER_OPTIONS).toEqual([
      { value: "Strong Pass", label: "Strong pass" },
      { value: "Pass", label: "Pass" },
      { value: "Pass with caution", label: "Pass with caution" },
      { value: "Fail", label: "May not pass" },
      { value: "incomplete", label: "Incomplete" },
    ]);
    expect(OVERALL_INCOMPLETE).toBe("incomplete");
  });

  it("empty is no filter: every row, including an Incomplete one", () => {
    expect(run([])).toEqual(["SP", "P", "PWC", "FAIL", "INC"]);
  });

  it.each([
    ["Strong Pass", ["SP"]],
    ["Pass", ["P"]],
    ["Pass with caution", ["PWC"]],
    ["Fail", ["FAIL"]],
    [OVERALL_INCOMPLETE, ["INC"]],
  ])("%s alone matches only its own rows (Pass with caution is not a Pass)", (value, expected) => {
    expect(run([value])).toEqual(expected);
  });

  it("several selected are OR'd", () => {
    expect(run(["Strong Pass", "Pass", "Pass with caution"])).toEqual(["SP", "P", "PWC"]);
    expect(run(["Fail", OVERALL_INCOMPLETE])).toEqual(["FAIL", "INC"]);
  });

  it("Incomplete matches a null overall_verdict, whatever else the row carries", () => {
    const odd = [row({ ticker: "NULL_V", overall_score: 70, overall_verdict: null })];
    expect(filterTickerScores(odd, { ...DEFAULT_FILTER_STATE, overallVerdicts: [OVERALL_INCOMPLETE] })).toHaveLength(1);
    expect(filterTickerScores(odd, { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Pass"] })).toHaveLength(0);
  });

  it("reads the stored verdict, not the score: a 91+ Overall stored as Pass with caution is not a Strong Pass match", () => {
    const cmg = [row({ ticker: "CMG", overall_score: 92, overall_verdict: "Pass with caution" })];
    expect(filterTickerScores(cmg, { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Strong Pass"] })).toHaveLength(0);
    expect(filterTickerScores(cmg, { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Pass with caution"] })).toHaveLength(1);
  });

  it("combines with the Financials / Growth / Profitability / Debt score ranges (all must hold)", () => {
    const mixed = [
      row({ ticker: "A", overall_verdict: "Pass", step5_score: 90 }),
      row({ ticker: "B", overall_verdict: "Pass", step5_score: 60 }),
      row({ ticker: "C", overall_verdict: "Fail", step5_score: 90 }),
    ];
    const filters = { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Pass"], step5Score: { min: 70, max: null } };
    expect(filterTickerScores(mixed, filters).map((r) => r.ticker)).toEqual(["A"]);
  });

  it("counts as one applied filter in the Fundamental section, and none when empty", () => {
    expect(countActiveFilters({ ...DEFAULT_FILTER_STATE, overallVerdicts: ["Pass", "Fail"] }, false, FUNDAMENTAL_FILTER_KEYS)).toBe(1);
    expect(countActiveFilters(DEFAULT_FILTER_STATE, false, FUNDAMENTAL_FILTER_KEYS)).toBe(0);
  });

  it("the old Overall score range no longer exists in the state", () => {
    expect("overallScore" in DEFAULT_FILTER_STATE).toBe(false);
  });
});
