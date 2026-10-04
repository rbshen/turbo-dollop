import { describe, expect, it } from "vitest";

import type { EtfWatchlistRow } from "@/lib/api/types";
import {
  applyEtfHeaderClick,
  DEFAULT_ETF_SORT_RULES,
  ETF_SORT_STORAGE_KEY_PREFIX,
  ETF_SORTABLE_FIELDS,
  etfDefaultDirectionFor,
  parseEtfSortRules,
  sortEtfWatchlistRows,
} from "@/lib/etfWatchlistSort";
import { MAX_SORT_RULES } from "@/lib/watchlistSort";

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

const tickers = (rows: EtfWatchlistRow[]) => rows.map((r) => r.ticker);

describe("the ETF table's sort fields", () => {
  it("are exactly the 13 data columns, and the default is AUM descending", () => {
    expect(ETF_SORTABLE_FIELDS).toHaveLength(13);
    expect(DEFAULT_ETF_SORT_RULES).toEqual([{ field: "aum", direction: "desc" }]);
  });

  it("uses its own storage key, not the stock table's", () => {
    expect(ETF_SORT_STORAGE_KEY_PREFIX).toBe("fathom-etf-watchlist-sort-");
    expect(ETF_SORT_STORAGE_KEY_PREFIX).not.toBe("fathom-watchlist-sort-");
  });

  it("starts text A-Z, the expense ratio cheapest first and every other figure highest first", () => {
    expect(["ticker", "name", "asset_class", "expense_ratio"].map((f) => etfDefaultDirectionFor(f as never))).toEqual(["asc", "asc", "asc", "asc"]);
    for (const field of ETF_SORTABLE_FIELDS.filter((f) => !["ticker", "name", "asset_class", "expense_ratio"].includes(f))) {
      expect(etfDefaultDirectionFor(field)).toBe("desc");
    }
  });
});

describe("sortEtfWatchlistRows", () => {
  const rows = [row("MID", { aum: 5, name: "Beta fund" }), row("BIG", { aum: 9, name: "Alpha fund" }), row("NONE"), row("SMALL", { aum: 1 })];

  it("sorts by a numeric rule in either direction with nulls last both ways", () => {
    expect(tickers(sortEtfWatchlistRows(rows, [{ field: "aum", direction: "desc" }]))).toEqual(["BIG", "MID", "SMALL", "NONE"]);
    expect(tickers(sortEtfWatchlistRows(rows, [{ field: "aum", direction: "asc" }]))).toEqual(["SMALL", "MID", "BIG", "NONE"]);
  });

  it("sorts text columns A-Z with a missing text last in both directions", () => {
    expect(tickers(sortEtfWatchlistRows(rows, [{ field: "name", direction: "asc" }])).slice(0, 2)).toEqual(["BIG", "MID"]);
    const desc = tickers(sortEtfWatchlistRows(rows, [{ field: "name", direction: "desc" }]));
    expect(desc.slice(0, 2)).toEqual(["MID", "BIG"]);
    expect(desc.slice(2).sort()).toEqual(["NONE", "SMALL"]);
  });

  it("breaks a tie with the next rule, and keeps arrival order when nothing separates the rows", () => {
    const tied = [row("A", { aum: 1, beta: 1 }), row("B", { aum: 1, beta: 2 }), row("C", { aum: 1, beta: 2 })];
    const out = sortEtfWatchlistRows(tied, [{ field: "aum", direction: "desc" }, { field: "beta", direction: "desc" }]);
    expect(tickers(out)).toEqual(["B", "C", "A"]);
  });

  it("returns the rows as they arrived when there are no rules, and never mutates its input", () => {
    expect(sortEtfWatchlistRows(rows, [])).toBe(rows);
    const before = tickers(rows);
    sortEtfWatchlistRows(rows, [{ field: "aum", direction: "asc" }]);
    expect(tickers(rows)).toEqual(before);
  });
});

describe("applyEtfHeaderClick (the stock table's click cycle)", () => {
  it("appends at the field's default direction, flips on the second click and removes on the third", () => {
    let rules = applyEtfHeaderClick([], "aum");
    expect(rules).toEqual([{ field: "aum", direction: "desc" }]);
    rules = applyEtfHeaderClick(rules, "aum");
    expect(rules).toEqual([{ field: "aum", direction: "asc" }]);
    rules = applyEtfHeaderClick(rules, "aum");
    expect(rules).toEqual([]);
  });

  it("multi-sorts up to the shared maximum and ignores a further new field", () => {
    let rules = DEFAULT_ETF_SORT_RULES;
    for (const field of ["beta", "return_ytd", "return_1y"] as const) rules = applyEtfHeaderClick(rules, field);
    expect(rules).toHaveLength(MAX_SORT_RULES);
    expect(applyEtfHeaderClick(rules, "ticker")).toEqual(rules);
  });
});

describe("parseEtfSortRules", () => {
  it("gives the default for no value, corrupt JSON and a non-array", () => {
    expect(parseEtfSortRules(null)).toEqual(DEFAULT_ETF_SORT_RULES);
    expect(parseEtfSortRules("not json")).toEqual(DEFAULT_ETF_SORT_RULES);
    expect(parseEtfSortRules('{"field":"aum"}')).toEqual(DEFAULT_ETF_SORT_RULES);
  });

  it("keeps a valid persisted list, and a persisted empty list is a real 'no sort'", () => {
    const saved = [{ field: "beta", direction: "asc" }, { field: "name", direction: "desc" }];
    expect(parseEtfSortRules(JSON.stringify(saved))).toEqual(saved);
    expect(parseEtfSortRules("[]")).toEqual([]);
  });

  it("falls back to the default for stock-table fields stored by the other table, unknown fields and bad directions", () => {
    expect(parseEtfSortRules('[{"field":"overall_score","direction":"desc"}]')).toEqual(DEFAULT_ETF_SORT_RULES);
    expect(parseEtfSortRules('[{"field":"market_cap","direction":"desc"},{"field":"aum","direction":"desc"}]')).toEqual(DEFAULT_ETF_SORT_RULES);
    expect(parseEtfSortRules('[{"field":"aum","direction":"sideways"}]')).toEqual(DEFAULT_ETF_SORT_RULES);
    expect(parseEtfSortRules('[{"field":"nope","direction":"asc"}]')).toEqual(DEFAULT_ETF_SORT_RULES);
  });

  it("falls back for more rules than the maximum", () => {
    const many = Array.from({ length: MAX_SORT_RULES + 1 }, () => ({ field: "aum", direction: "asc" }));
    expect(parseEtfSortRules(JSON.stringify(many))).toEqual(DEFAULT_ETF_SORT_RULES);
  });
});
