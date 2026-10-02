import type { EtfScreenerRowOut } from "@/lib/api/types";
import {
  countActiveIn,
  EMPTY_RANGE,
  inRange,
  isoToMs,
  sortRows,
  WEINSTEIN_PENDING_FILTER_VALUE,
  type RangeFilter,
  type SortDirection,
} from "@/lib/screenerFilters";

// Filter state, filtering and sorting for the ETFs page. The row is EtfScreenerRowOut (GET /api/etf-screener), not a
// TickerScoreOut, so it has its own state; the pieces that do not depend on the row (RangeFilter, the Weinstein/Warren
// option lists, the null-last sort, the active-filter counting rule) are the Stocks Screener's own.
// Spec: docs/specs/etf-screener.md.

export interface EtfFilterState {
  // Empty array means "no filter applied", as on the Stocks page.
  assetClasses: string[];
  // Percent number (0.09 = 0.09%).
  expenseRatio: RangeFilter;
  // Last close, USD.
  quote: RangeFilter;
  // 1-day change, percent number.
  change1d: RangeFilter;
  // Assets under management, USD.
  aum: RangeFilter;
  // Already null for a non-equity fund (the backend's rule), so an active range drops those rows like any null.
  beta: RangeFilter;
  // The ETF's 1Y return minus SPY's, percentage points.
  vsSpy1y: RangeFilter;
  weinsteinStages: string[];
  warrenSignalKinds: string[];
  bbRsiEntrySignal: boolean;
}

export const DEFAULT_ETF_FILTER_STATE: EtfFilterState = {
  assetClasses: [],
  expenseRatio: EMPTY_RANGE,
  quote: EMPTY_RANGE,
  change1d: EMPTY_RANGE,
  aum: EMPTY_RANGE,
  beta: EMPTY_RANGE,
  vsSpy1y: EMPTY_RANGE,
  weinsteinStages: [],
  warrenSignalKinds: [],
  bbRsiEntrySignal: false,
};

export type EtfFilterKey = keyof EtfFilterState;

// Which filters sit under which sidebar section, so each header counts its own (a test pins that together they are
// every key of the state).
export const ETF_FUNDAMENTAL_FILTER_KEYS: readonly EtfFilterKey[] = ["assetClasses", "expenseRatio", "quote", "change1d", "aum"];
export const ETF_TECHNICAL_FILTER_KEYS: readonly EtfFilterKey[] = [
  "beta",
  "vsSpy1y",
  "weinsteinStages",
  "warrenSignalKinds",
  "bbRsiEntrySignal",
];

const ALL_ETF_FILTER_KEYS = Object.keys(DEFAULT_ETF_FILTER_STATE) as EtfFilterKey[];

export function countActiveEtfFilters(
  filters: EtfFilterState,
  watchlistActive: boolean,
  keys: readonly EtfFilterKey[] = ALL_ETF_FILTER_KEYS
): number {
  return countActiveIn(filters, watchlistActive, keys);
}

export function filterEtfRows(
  rows: EtfScreenerRowOut[],
  filters: EtfFilterState,
  watchlistTickers: Set<string> | null = null
): EtfScreenerRowOut[] {
  return rows.filter((row) => {
    if (watchlistTickers && !watchlistTickers.has(row.ticker)) return false;
    if (filters.assetClasses.length > 0 && (!row.asset_class || !filters.assetClasses.includes(row.asset_class))) return false;
    if (!inRange(row.expense_ratio, filters.expenseRatio)) return false;
    if (!inRange(row.last_price, filters.quote)) return false;
    if (!inRange(row.pct_change_1d, filters.change1d)) return false;
    if (!inRange(row.aum, filters.aum)) return false;
    if (!inRange(row.beta, filters.beta)) return false;
    if (!inRange(row.vs_spy_1y, filters.vsSpy1y)) return false;
    if (filters.weinsteinStages.length > 0) {
      const matchesStage = filters.weinsteinStages.includes(row.weinstein_stage ?? "");
      const matchesPending =
        filters.weinsteinStages.includes(WEINSTEIN_PENDING_FILTER_VALUE) && row.weinstein_pending_direction != null;
      if (!matchesStage && !matchesPending) return false;
    }
    if (filters.bbRsiEntrySignal && !row.bb_rsi_entry_signal) return false;
    if (filters.warrenSignalKinds.length > 0 && !filters.warrenSignalKinds.includes(row.warren_active_signal_kind ?? "")) {
      return false;
    }
    return true;
  });
}

export type EtfSortField =
  | "aum"
  | "expense_ratio"
  | "last_price"
  | "pct_change_1d"
  | "beta"
  | "vs_spy_1y"
  | "warren_signal_recency"
  | "weinstein_stage_since";

// Option values are the stored/sent EtfSortField keys; the labels are display-only.
export const ETF_SORT_OPTIONS: { value: EtfSortField; label: string }[] = [
  { value: "aum", label: "AUM" },
  { value: "expense_ratio", label: "Expense ratio" },
  { value: "last_price", label: "Quote" },
  { value: "pct_change_1d", label: "1D change" },
  { value: "beta", label: "Beta" },
  { value: "vs_spy_1y", label: "1Y vs SPY" },
  { value: "warren_signal_recency", label: "Warren signal recency" },
  { value: "weinstein_stage_since", label: "Weinstein: stage since" },
];

// What the sort is on first load and what Reset puts it back to: the biggest funds first.
export const DEFAULT_ETF_SORT_FIELD: EtfSortField = "aum";
export const DEFAULT_ETF_SORT_DIRECTION: SortDirection = "desc";

function etfSortValue(row: EtfScreenerRowOut, field: EtfSortField): number | null {
  if (field === "warren_signal_recency") return isoToMs(row.warren_last_buy_fired_at);
  if (field === "weinstein_stage_since") return isoToMs(row.weinstein_stage_since_date);
  return row[field];
}

export function sortEtfRows(rows: EtfScreenerRowOut[], field: EtfSortField, direction: SortDirection): EtfScreenerRowOut[] {
  return sortRows(rows, (row) => etfSortValue(row, field), direction);
}
