import type { EtfWatchlistRow } from "@/lib/api/types";
import type { SortDirection } from "@/lib/screenerFilters";
import { applyHeaderClickWith, compareNullable, parseSortRulesWith } from "@/lib/watchlistSort";

// Sorting for the ETF table of the list named "ETF" (components/watchlist/EtfWatchlistTable.tsx). Same click cycle,
// multi-sort and null-last rule as the stock table (the shared helpers in lib/watchlistSort.ts), over its own field set,
// default directions and localStorage key, so a rule stored for the stock table can never reach this one.

export type EtfSortableField =
  | "ticker"
  | "name"
  | "last_price"
  | "pct_change_1d"
  | "asset_class"
  | "expense_ratio"
  | "aum"
  | "holdings_count"
  | "avg_volume_30d"
  | "dividend_yield"
  | "beta"
  | "return_ytd"
  | "return_1y";

export interface EtfSortRule {
  field: EtfSortableField;
  direction: SortDirection;
}

// First-click direction per column: text A-Z, the cost column cheapest first, every other figure highest first.
const DEFAULT_DIRECTION: Record<EtfSortableField, SortDirection> = {
  ticker: "asc",
  name: "asc",
  last_price: "desc",
  pct_change_1d: "desc",
  asset_class: "asc",
  expense_ratio: "asc",
  aum: "desc",
  holdings_count: "desc",
  avg_volume_30d: "desc",
  dividend_yield: "desc",
  beta: "desc",
  return_ytd: "desc",
  return_1y: "desc",
};

export const ETF_SORTABLE_FIELDS = Object.keys(DEFAULT_DIRECTION) as EtfSortableField[];

export const DEFAULT_ETF_SORT_RULES: EtfSortRule[] = [{ field: "aum", direction: "desc" }];

/** Key prefix of the per-list persisted rules; deliberately not the stock table's `fathom-watchlist-sort-`. */
export const ETF_SORT_STORAGE_KEY_PREFIX = "fathom-etf-watchlist-sort-";

export function etfDefaultDirectionFor(field: EtfSortableField): SortDirection {
  return DEFAULT_DIRECTION[field];
}

export function applyEtfHeaderClick(rules: EtfSortRule[], field: EtfSortableField): EtfSortRule[] {
  return applyHeaderClickWith(rules, field, etfDefaultDirectionFor);
}

/** Persisted rules back to a list; null (never set), corrupt JSON, too many rules or any rule naming a field this table
 * does not have (a stale or foreign value) all give the default. A persisted "[]" is a real "no sort" and stays empty. */
export function parseEtfSortRules(raw: string | null): EtfSortRule[] {
  return parseSortRulesWith(raw, ETF_SORTABLE_FIELDS, DEFAULT_ETF_SORT_RULES);
}

/** Rows ordered by the rules in priority order; nulls (and a missing text) sort last whichever the direction. No rules:
 * the rows as they arrived. A final tie falls back to the arrival order (a stable sort). */
export function sortEtfWatchlistRows(rows: EtfWatchlistRow[], rules: EtfSortRule[]): EtfWatchlistRow[] {
  if (rules.length === 0) return rows;
  return [...rows].sort((a, b) => {
    for (const rule of rules) {
      const dir = rule.direction === "asc" ? 1 : -1;
      const cmp = compareNullable(a[rule.field], b[rule.field], dir);
      if (cmp !== 0) return cmp;
    }
    return 0;
  });
}
