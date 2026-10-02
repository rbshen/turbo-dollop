import type { MultiSelectOption } from "@/components/screener/MultiSelectDropdown";
import { PERF_VS_SPY_LABELS } from "@/components/ticker/PerfVsSpyPill";
import { VALUATION_LABELS } from "@/components/screener/ValuationBadge";
import { MOAT_LABELS } from "@/lib/overallScore";
import { pillLabel } from "@/lib/tierColor";
import { WEINSTEIN_STAGE_LABEL } from "@/lib/weinsteinStage";
import type { TickerScoreOut } from "@/lib/api/types";
import { formatNumberInput } from "@/lib/numberInput";

export interface RangeFilter {
  min: number | null;
  max: number | null;
}

export const EMPTY_RANGE: RangeFilter = { min: null, max: null };

// Shared "this filter currently holds a non-default value" highlight,
// reused by every filter label across Watchlist/Fundamental/
// Technical (2026-09-15) rather than duplicating the color logic per
// component -- see globals.css's --fathom-filter-active for why this is a
// distinct token from --fathom-chart-orange despite sharing the same hue.
export const FILTER_ACTIVE_LABEL_CLASS = "text-filter-active";

/** Market-cap suffixes: M, B and T (5T is 5,000,000,000,000). Passed to RangeField
 * as `suffixes`; parsing is checkNumber(..., { suffixes }) in numberInput.ts
 * (case-insensitive, optional space), the one parser for a market-cap box. */
export const MARKET_CAP_SUFFIXES: Record<string, number> = { T: 1e12, B: 1e9, M: 1e6 };

/** What a stored market cap reads back as in a box: the shortest exact form
 * ("1B", "2.5T"), or plain digits. See formatNumberInput. */
export function formatMarketCapInput(value: number | null): string {
  return formatNumberInput(value, MARKET_CAP_SUFFIXES);
}

// Sentinel for "no moat set" (absence of a TickerMoat row -- the default
// state for every ticker, see CLAUDE.md's Economic Moat deviation note) --
// not a real stored moat value, so it can't collide with "wide_moat" etc.
export const MOAT_NOT_SET = "not_set";

// Fixed 4-value set, not data-derived from the current rows (unlike
// Sector/Company type, which only ever offer values actually present) --
// every moat state should always be selectable even if no ticker in the
// current universe happens to have it set yet.
export const MOAT_FILTER_OPTIONS: MultiSelectOption[] = [
  { value: "wide_moat", label: pillLabel(MOAT_LABELS.wide_moat) },
  { value: "narrow_moat", label: pillLabel(MOAT_LABELS.narrow_moat) },
  { value: "no_moat", label: pillLabel(MOAT_LABELS.no_moat) },
  { value: MOAT_NOT_SET, label: "Not set" },
];

// No "not set" option here, unlike Moat -- Valuation status only has the 3
// states the spec calls for; a ticker with no verdict yet is excluded once
// this filter is active, same as the existing null-sector convention.
export const VALUATION_FILTER_OPTIONS: MultiSelectOption[] = [
  { value: "undervalued", label: VALUATION_LABELS.undervalued },
  { value: "fair", label: VALUATION_LABELS.fair },
  { value: "overvalued", label: VALUATION_LABELS.overvalued },
];

// "no_data" doubles as the fallback bucket for a null status (a TickerScore
// row computed before this field existed, or a row for a ticker with no
// FMP "5Y" figure at all) -- same null-coalescing convention as Moat's
// MOAT_NOT_SET below, not a distinct 4th value.
//
// "outperform"/"underperform" are labeled here directly ("Outperform"/
// "Underperform") rather than via PERF_VS_SPY_LABELS -- this filter's own
// group label already reads "5Y vs SPY" (ScreenerFilters.tsx), so repeating
// "SPY" in each option is redundant here (2026-09-05). PERF_VS_SPY_LABELS
// itself is left alone here regardless -- it backs the ticker-page header
// pill (PerfVsSpyPill.tsx), out of scope for this filter dropdown, and
// separately switched outperform/underperform to a shared static "5Y vs
// SPY" label of its own (2026-09-05 follow-up) -- the two are unrelated
// beyond having briefly shared the same source strings.
export const VS_SPY_FILTER_OPTIONS: MultiSelectOption[] = [
  { value: "outperform", label: "Outperform" },
  { value: "underperform", label: "Underperform" },
  { value: "match", label: PERF_VS_SPY_LABELS.match },
  { value: "no_data", label: PERF_VS_SPY_LABELS.no_data },
];

// Fixed 4-value set, like Moat above -- every stage should always be
// selectable regardless of what's present in the current universe. No
// "not set" bucket like Moat's MOAT_NOT_SET -- a null weinstein_stage
// (never computed, or a row predating this field) simply fails every
// .includes() check in filterTickerScores below and is excluded once this
// filter is active, same as the existing null-sector/null-valuation
// convention -- there's no meaningful "no stage" grouping a user would
// filter *for*.
export const WEINSTEIN_PENDING_FILTER_VALUE = "pending";

export const WEINSTEIN_STAGE_FILTER_OPTIONS: MultiSelectOption[] = [
  { value: "base", label: WEINSTEIN_STAGE_LABEL.base },
  { value: "advance", label: WEINSTEIN_STAGE_LABEL.advance },
  { value: "top", label: WEINSTEIN_STAGE_LABEL.top },
  { value: "decline", label: WEINSTEIN_STAGE_LABEL.decline },
  // Not a stage: any ticker with a Flip-ETA prediction (TickerScore.
  // weinstein_pending_direction non-null), whatever the ETA horizon. OR-combined
  // with the stage values, like every other value of this multi-select.
  { value: WEINSTEIN_PENDING_FILTER_VALUE, label: "Pending" },
];

// Fixed 3-value set matching Warren's own Up-kind vocabulary exactly
// (see TickerScore.warren_active_signal_kind) -- no "not active" option,
// same reasoning as Weinstein Stage above: a ticker with no currently
// active Warren buy state simply fails every .includes() check once this
// filter is active. Labels are local to this dropdown (matching
// WarrenSignalCard.tsx's own KIND_LABELS text), not imported from there --
// this filter's own group label already reads "Warren entry (2h)", same
// redundancy rationale as VS_SPY_FILTER_OPTIONS
// above. Replaced an earlier single combined checkbox (Blue+Yellow only,
// Gray Up excluded entirely) once Gray Up became a real, independently
// selectable option.
export const WARREN_SIGNAL_KIND_FILTER_OPTIONS: MultiSelectOption[] = [
  { value: "blue_up", label: "Blue up" },
  { value: "yellow_up", label: "Yellow up" },
  { value: "gray_up", label: "Gray up" },
];

export interface ScreenerFilterState {
  overallScore: RangeFilter;
  step1Score: RangeFilter;
  step2Score: RangeFilter;
  step4Score: RangeFilter;
  step5Score: RangeFilter;
  quote: RangeFilter;
  marketCap: RangeFilter;
  peRatio: RangeFilter;
  beta: RangeFilter;
  growthRate: RangeFilter;
  // Empty array means "no filter applied" (every sector/type passes) --
  // NOT "exclude everything".
  sectors: string[];
  companyTypes: string[];
  moat: string[];
  valuationVerdict: string[];
  vsSpy: string[];
  weinsteinStages: string[];
  // Plain boolean, unlike the array filters above -- a checkbox, not a
  // multi-select. false (default) means "no filtering by this criterion";
  // true means "show only qualifies=true" (see filterTickerScores below).
  speculativeGrowth: boolean;
  // Same boolean-checkbox shape as speculativeGrowth above -- but unlike
  // every other Technical filter, this one only ever matches tickers on
  // a monitored watchlist (named E<number> or ETF) (see TechnicalFilters.tsx's
  // own caption), since bb_rsi_entry_signal is null for every other ticker.
  bbRsiEntrySignal: boolean;
  // Multi-select over Warren's 3 Up-kinds (Blue/Yellow/Gray Up), OR
  // semantics -- matches Weinstein Stage's array-filter pattern above,
  // not bbRsiEntrySignal's single-checkbox shape. Same monitored-watchlist-only
  // scoping as bbRsiEntrySignal (warren_active_signal_kind is null for
  // every other ticker).
  warrenSignalKinds: string[];
}

export const DEFAULT_FILTER_STATE: ScreenerFilterState = {
  overallScore: EMPTY_RANGE,
  step1Score: EMPTY_RANGE,
  step2Score: EMPTY_RANGE,
  step4Score: EMPTY_RANGE,
  step5Score: EMPTY_RANGE,
  quote: EMPTY_RANGE,
  marketCap: EMPTY_RANGE,
  peRatio: EMPTY_RANGE,
  beta: EMPTY_RANGE,
  growthRate: EMPTY_RANGE,
  sectors: [],
  companyTypes: [],
  moat: [],
  valuationVerdict: [],
  vsSpy: [],
  weinsteinStages: [],
  speculativeGrowth: false,
  bbRsiEntrySignal: false,
  warrenSignalKinds: [],
};

export type FilterKey = keyof ScreenerFilterState;

// Which filters live under which sidebar section, so each section header can
// count its own. Together they are exactly every key of the state (a test pins
// that, so a filter added later must be given a section), and the Watchlist
// section's one filter is the page-level scope, not a state key.
export const FUNDAMENTAL_FILTER_KEYS: readonly FilterKey[] = [
  "overallScore",
  "step1Score",
  "step2Score",
  "step4Score",
  "step5Score",
  "quote",
  "marketCap",
  "peRatio",
  "growthRate",
  "sectors",
  "companyTypes",
  "moat",
  "valuationVerdict",
  "speculativeGrowth",
];
export const TECHNICAL_FILTER_KEYS: readonly FilterKey[] = [
  "beta",
  "vsSpy",
  "weinsteinStages",
  "warrenSignalKinds",
  "bbRsiEntrySignal",
];

const ALL_FILTER_KEYS = Object.keys(DEFAULT_FILTER_STATE) as FilterKey[];

/** How many filters are applied right now: ranges with a min or a max, multi-
 * selects with at least one option, checked chips, plus one for a watchlist
 * filter that is actually in effect (`watchlistActive`). Counts the keys of
 * `keys` (default: every filter in the state), so a section header passes its
 * own list. Only the state's own keys are read, so a key a saved view carries
 * that no longer exists (the removed "country") is never counted. */
export function countActiveFilters(
  filters: ScreenerFilterState,
  watchlistActive: boolean,
  keys: readonly FilterKey[] = ALL_FILTER_KEYS
): number {
  return countActiveIn(filters, watchlistActive, keys);
}

/** The counting rule behind countActiveFilters, for any filter-state shape
 * (the ETFs page has its own state, see etfScreenerFilters.ts). */
export function countActiveIn<S extends object>(filters: S, watchlistActive: boolean, keys: readonly (keyof S)[]): number {
  let count = watchlistActive ? 1 : 0;
  for (const key of keys) {
    const value = filters[key] as RangeFilter | string[] | boolean | null | undefined;
    if (value == null) continue;
    if (Array.isArray(value)) {
      if (value.length > 0) count += 1;
    } else if (typeof value === "boolean") {
      if (value) count += 1;
    } else if (value.min != null || value.max != null) {
      count += 1;
    }
  }
  return count;
}

// A range filter is only "active" if min or max is actually set -- an
// active filter can never be satisfied by a null value (e.g. filtering
// "Overall score > 70" must exclude an Incomplete ticker with no Overall
// score at all, not treat the missing value as passing).
export function inRange(value: number | null | undefined, range: RangeFilter): boolean {
  if (range.min == null && range.max == null) return true;
  if (value == null) return false;
  if (range.min != null && value < range.min) return false;
  if (range.max != null && value > range.max) return false;
  return true;
}

// True for an ETF/fund product. Reads TickerScoreOut.is_etf, but a row
// computed before that column existed (null) falls back to company_type ===
// "ETF" -- classify_company_type derives that from the very same FMP profile
// flag, so a not-yet-recomputed ETF row (SPY, at rollout) is still caught
// instead of leaking through as "not an ETF" until the next recompute.
// Mirrored in SQL by backend/core/main.py::screener_meta -- keep in sync.
export function isEtfRow(row: TickerScoreOut): boolean {
  return row.is_etf ?? row.company_type === "ETF";
}

// The Screener is stock equities only -- the 5-step fundamentals framework
// doesn't apply to a fund. Unconditional, NOT a filter/toggle: the page
// applies this to the fetched rows once, before anything derives from them
// (counts, Sector/Company type options, filterTickerScores), so an ETF can
// never appear or be selectable. Screener-only -- Watchlist reads its own
// rows and still shows an ETF a user explicitly added.
export function excludeEtfs(rows: TickerScoreOut[]): TickerScoreOut[] {
  return rows.filter((row) => !isEtfRow(row));
}

// watchlistTickers: the currently-selected WATCHLIST universe filter's
// member set (see WatchlistFilter.tsx), or null when no watchlist is
// selected / the universe toggle isn't "all". Deliberately a separate
// parameter rather than a ScreenerFilterState field -- like `universe`,
// watchlist selection is a "base scope" concept, not part of the
// Fundamental/Technical filter blob SavedScreenerFilter.filters_json
// stores verbatim (see that model's own docstring on why watchlist_id is
// a discrete column instead).
export function filterTickerScores(
  rows: TickerScoreOut[],
  filters: ScreenerFilterState,
  watchlistTickers: Set<string> | null = null
): TickerScoreOut[] {
  return rows.filter((row) => {
    if (watchlistTickers && !watchlistTickers.has(row.ticker)) return false;
    if (!inRange(row.overall_score, filters.overallScore)) return false;
    if (!inRange(row.step1_score, filters.step1Score)) return false;
    if (!inRange(row.step2_score, filters.step2Score)) return false;
    if (!inRange(row.step4_score, filters.step4Score)) return false;
    if (!inRange(row.step5_score, filters.step5Score)) return false;
    if (!inRange(row.last_price, filters.quote)) return false;
    if (!inRange(row.market_cap, filters.marketCap)) return false;
    if (!inRange(row.pe_ratio, filters.peRatio)) return false;
    if (!inRange(row.beta, filters.beta)) return false;
    if (!inRange(row.growth_rate, filters.growthRate)) return false;
    if (filters.sectors.length > 0 && (!row.sector || !filters.sectors.includes(row.sector))) return false;
    if (filters.companyTypes.length > 0 && (!row.company_type || !filters.companyTypes.includes(row.company_type))) {
      return false;
    }
    if (filters.moat.length > 0 && !filters.moat.includes(row.moat ?? MOAT_NOT_SET)) return false;
    if (filters.valuationVerdict.length > 0 && (!row.valuation_verdict || !filters.valuationVerdict.includes(row.valuation_verdict))) {
      return false;
    }
    if (filters.vsSpy.length > 0 && !filters.vsSpy.includes(row.perf_5y_vs_spy_status ?? "no_data")) return false;
    if (filters.weinsteinStages.length > 0) {
      const matchesStage = filters.weinsteinStages.includes(row.weinstein_stage ?? "");
      const matchesPending =
        filters.weinsteinStages.includes(WEINSTEIN_PENDING_FILTER_VALUE) && row.weinstein_pending_direction != null;
      if (!matchesStage && !matchesPending) return false;
    }
    if (filters.speculativeGrowth && !row.speculative_growth_qualifies) return false;
    if (filters.bbRsiEntrySignal && !row.bb_rsi_entry_signal) return false;
    if (filters.warrenSignalKinds.length > 0 && !filters.warrenSignalKinds.includes(row.warren_active_signal_kind ?? "")) {
      return false;
    }
    return true;
  });
}

export type SortField =
  | "overall_score"
  | "step1_score"
  | "step2_score"
  | "step4_score"
  | "step5_score"
  | "last_price"
  | "market_cap"
  | "pe_ratio"
  | "beta"
  | "growth_rate"
  | "warren_signal_recency"
  | "weinstein_stage_since";

export type SortDirection = "asc" | "desc";

// warren_signal_recency and weinstein_stage_since are the date-typed sort
// fields (every other SortField reads a plain number|null score/metric
// straight off the row, so a's[field] - b's[field] just works) -- these
// convert warren_last_buy_fired_at / weinstein_stage_since_date (ISO strings)
// to an epoch-ms number, leaving every other field's raw numeric value
// untouched, so the shared null-handling/subtraction below stays generic.
// weinstein_stage_since: "desc" = most recently started stage first (freshest
// flips); a lower-bound date (stage never changed in the replay window) sorts
// as that earliest date, i.e. among the longest-standing stages.
function sortValue(row: TickerScoreOut, field: SortField): number | null {
  if (field === "warren_signal_recency") {
    return row.warren_last_buy_fired_at ? Date.parse(row.warren_last_buy_fired_at) : null;
  }
  if (field === "weinstein_stage_since") {
    return row.weinstein_stage_since_date ? Date.parse(row.weinstein_stage_since_date) : null;
  }
  return row[field];
}

export function sortTickerScores(rows: TickerScoreOut[], field: SortField, direction: SortDirection): TickerScoreOut[] {
  return sortRows(rows, (row) => sortValue(row, field), direction);
}

/** An ISO date/datetime string as epoch ms, null for no value (the date-typed sort fields). */
export function isoToMs(value: string | null | undefined): number | null {
  return value ? Date.parse(value) : null;
}

/** The one sort rule: by `valueOf`, nulls last in either direction. Shared by the Stocks and ETFs pages. */
export function sortRows<T>(rows: T[], valueOf: (row: T) => number | null, direction: SortDirection): T[] {
  const dir = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = valueOf(a);
    const bv = valueOf(b);
    // Nulls always sort to the end, regardless of direction -- an
    // Incomplete ticker (or, for warren_signal_recency, a ticker with no
    // Warren buy signal history at all) shouldn't jump to the top just
    // because "asc" was picked and null sorts low by default in a naive
    // comparator.
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return (av - bv) * dir;
  });
}

export function extractSectors(rows: TickerScoreOut[]): string[] {
  return Array.from(new Set(rows.map((r) => r.sector).filter((s): s is string => !!s))).sort();
}

export function extractCompanyTypes(rows: TickerScoreOut[]): string[] {
  return Array.from(new Set(rows.map((r) => r.company_type).filter((t): t is string => !!t))).sort();
}
