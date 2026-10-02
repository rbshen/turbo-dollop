import { describe, expect, it } from "vitest";

import type { EtfScreenerRowOut } from "@/lib/api/types";
import {
  countActiveEtfFilters,
  DEFAULT_ETF_FILTER_STATE,
  ETF_FUNDAMENTAL_FILTER_KEYS,
  ETF_SORT_OPTIONS,
  ETF_TECHNICAL_FILTER_KEYS,
  filterEtfRows,
  sortEtfRows,
  type EtfFilterState,
} from "@/lib/etfScreenerFilters";

function etf(ticker: string, overrides: Partial<EtfScreenerRowOut> = {}): EtfScreenerRowOut {
  return {
    ticker,
    name: ticker,
    asset_class: "Equity",
    expense_ratio: 0.1,
    aum: 1e9,
    last_price: 100,
    pct_change_1d: 0.5,
    beta: 1,
    return_1y: 10,
    vs_spy_1y: 0,
    weinstein_stage: null,
    weinstein_stage_since_date: null,
    weinstein_stage_since_is_lower_bound: null,
    weinstein_ma_slope_pct: null,
    weinstein_vs_ma_pct: null,
    weinstein_pending_direction: null,
    bb_rsi_entry_signal: null,
    warren_active_signal_kind: null,
    warren_last_buy_fired_at: null,
    as_of_date: null,
    info_updated_at: null,
    updated_at: null,
    ...overrides,
  };
}

const state = (patch: Partial<EtfFilterState>): EtfFilterState => ({ ...DEFAULT_ETF_FILTER_STATE, ...patch });
const tickers = (rows: EtfScreenerRowOut[]) => rows.map((r) => r.ticker);

const ROWS = [
  etf("SPY", { aum: 5e11, expense_ratio: 0.09, last_price: 600, pct_change_1d: 0.3, vs_spy_1y: 0, weinstein_stage: "advance" }),
  etf("TLT", { asset_class: "Fixed Income", aum: 5e10, expense_ratio: 0.15, last_price: 90, pct_change_1d: -0.4, beta: null, vs_spy_1y: -12.5, weinstein_stage: "decline" }),
  etf("GLD", { asset_class: "Commodities", aum: 7e10, expense_ratio: 0.4, last_price: 300, pct_change_1d: 1.2, beta: null, vs_spy_1y: 20, weinstein_stage: "top", bb_rsi_entry_signal: true }),
  etf("NEW", { aum: null, expense_ratio: null, last_price: null, pct_change_1d: null, beta: null, vs_spy_1y: null }),
];

describe("filterEtfRows", () => {
  it("passes every row, nulls included, with the default state", () => {
    expect(tickers(filterEtfRows(ROWS, DEFAULT_ETF_FILTER_STATE))).toEqual(["SPY", "TLT", "GLD", "NEW"]);
  });

  it("filters by asset class (OR within the list) and drops a row with none", () => {
    expect(tickers(filterEtfRows(ROWS, state({ assetClasses: ["Fixed Income", "Commodities"] })))).toEqual(["TLT", "GLD"]);
    expect(tickers(filterEtfRows([...ROWS, etf("X", { asset_class: null })], state({ assetClasses: ["Equity"] })))).toEqual(["SPY", "NEW"]);
  });

  it.each([
    ["expenseRatio", { min: null, max: 0.15 }, ["SPY", "TLT"]],
    ["quote", { min: 100, max: null }, ["SPY", "GLD"]],
    ["change1d", { min: null, max: 0 }, ["TLT"]],
    ["aum", { min: 6e10, max: null }, ["SPY", "GLD"]],
    ["beta", { min: 0.5, max: 2 }, ["SPY"]],
    ["vsSpy1y", { min: 0, max: null }, ["SPY", "GLD"]],
  ] as const)("a %s range keeps only rows inside it, and drops a null value", (key, range, expected) => {
    expect(tickers(filterEtfRows(ROWS, state({ [key]: range })))).toEqual(expected);
  });

  it("filters by Weinstein stage, with Pending as an OR-ed extra value", () => {
    const rows = [...ROWS, etf("PND", { weinstein_stage: "base", weinstein_pending_direction: "advance" })];
    expect(tickers(filterEtfRows(rows, state({ weinsteinStages: ["advance", "top"] })))).toEqual(["SPY", "GLD"]);
    expect(tickers(filterEtfRows(rows, state({ weinsteinStages: ["decline", "pending"] })))).toEqual(["TLT", "PND"]);
  });

  it("filters by BB+RSI and Warren signals", () => {
    const rows = [...ROWS, etf("WAR", { warren_active_signal_kind: "blue_up" })];
    expect(tickers(filterEtfRows(rows, state({ bbRsiEntrySignal: true })))).toEqual(["GLD"]);
    expect(tickers(filterEtfRows(rows, state({ warrenSignalKinds: ["blue_up", "gray_up"] })))).toEqual(["WAR"]);
  });

  it("scopes to a watchlist's tickers, and combines with the other filters", () => {
    expect(tickers(filterEtfRows(ROWS, DEFAULT_ETF_FILTER_STATE, new Set(["TLT", "GLD"])))).toEqual(["TLT", "GLD"]);
    expect(tickers(filterEtfRows(ROWS, state({ assetClasses: ["Commodities"] }), new Set(["TLT", "SPY"])))).toEqual([]);
  });
});

describe("sortEtfRows", () => {
  it("sorts by a numeric field in either direction, with nulls last both ways", () => {
    expect(tickers(sortEtfRows(ROWS, "aum", "desc"))).toEqual(["SPY", "GLD", "TLT", "NEW"]);
    expect(tickers(sortEtfRows(ROWS, "aum", "asc"))).toEqual(["TLT", "GLD", "SPY", "NEW"]);
    expect(tickers(sortEtfRows(ROWS, "vs_spy_1y", "desc"))).toEqual(["GLD", "SPY", "TLT", "NEW"]);
  });

  it("does not mutate its input", () => {
    const copy = [...ROWS];
    sortEtfRows(ROWS, "expense_ratio", "asc");
    expect(ROWS).toEqual(copy);
  });

  it("sorts the two date fields by time, undated last", () => {
    const rows = [
      etf("OLD", { weinstein_stage_since_date: "2025-01-02", warren_last_buy_fired_at: "2025-03-01T10:00:00" }),
      etf("NEWER", { weinstein_stage_since_date: "2026-06-01", warren_last_buy_fired_at: "2026-02-01T10:00:00" }),
      etf("NONE"),
    ];
    expect(tickers(sortEtfRows(rows, "weinstein_stage_since", "desc"))).toEqual(["NEWER", "OLD", "NONE"]);
    expect(tickers(sortEtfRows(rows, "warren_signal_recency", "asc"))).toEqual(["OLD", "NEWER", "NONE"]);
  });

  it("offers one option per sort field, every one sortable", () => {
    expect(ETF_SORT_OPTIONS.map((o) => o.value)).toEqual([
      "aum",
      "expense_ratio",
      "last_price",
      "pct_change_1d",
      "beta",
      "vs_spy_1y",
      "warren_signal_recency",
      "weinstein_stage_since",
    ]);
    for (const { value } of ETF_SORT_OPTIONS) expect(() => sortEtfRows(ROWS, value, "asc")).not.toThrow();
  });
});

describe("countActiveEtfFilters", () => {
  it("Fundamental and Technical together are exactly every filter in the state, with no overlap", () => {
    const sections = [...ETF_FUNDAMENTAL_FILTER_KEYS, ...ETF_TECHNICAL_FILTER_KEYS];
    expect([...sections].sort()).toEqual(Object.keys(DEFAULT_ETF_FILTER_STATE).sort());
    expect(new Set(sections).size).toBe(sections.length);
  });

  it("counts ranges, lists and the checkbox, per section, plus a watchlist in effect", () => {
    const s = state({ assetClasses: ["Equity"], aum: { min: 1, max: null }, beta: { min: null, max: 2 }, bbRsiEntrySignal: true });
    expect(countActiveEtfFilters(s, false, ETF_FUNDAMENTAL_FILTER_KEYS)).toBe(2);
    expect(countActiveEtfFilters(s, false, ETF_TECHNICAL_FILTER_KEYS)).toBe(2);
    expect(countActiveEtfFilters(s, true)).toBe(5);
    expect(countActiveEtfFilters(DEFAULT_ETF_FILTER_STATE, false)).toBe(0);
  });
});
