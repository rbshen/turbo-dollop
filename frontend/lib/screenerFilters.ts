import type { TickerScoreOut } from "@/lib/api/types";

export interface RangeFilter {
  min: number | null;
  max: number | null;
}

export const EMPTY_RANGE: RangeFilter = { min: null, max: null };

const MARKET_CAP_SUFFIX_MULTIPLIERS: Record<string, number> = { B: 1e9, M: 1e6 };

/** Parses Market Cap filter input: a bare number is raw dollars (unchanged
 * from before), optionally suffixed with "B"/"M" (case-insensitive, with or
 * without a separating space) for billions/millions, e.g. "1B" / "1 b" ->
 * 1_000_000_000, "2M" / "2 m" -> 2_000_000. Empty string parses to null (no
 * filter on that side). Returns `undefined` for anything else -- an
 * unparseable string, a negative number, or a number with an unrecognized
 * suffix -- so callers can tell "no filter" apart from "invalid input" and
 * leave the last valid filter value in place rather than silently applying
 * zero or excluding every row. */
export function parseMarketCapInput(raw: string): number | null | undefined {
  const trimmed = raw.trim();
  if (trimmed === "") return null;

  const match = /^(-?\d+(?:\.\d+)?)\s*([A-Za-z]*)$/.exec(trimmed);
  if (!match) return undefined;

  const [, numberPart, suffixPart] = match;
  const value = Number(numberPart);
  if (!Number.isFinite(value) || value < 0) return undefined;

  if (suffixPart === "") return value;

  const multiplier = MARKET_CAP_SUFFIX_MULTIPLIERS[suffixPart.toUpperCase()];
  if (multiplier == null) return undefined;
  return value * multiplier;
}

export interface ScreenerFilterState {
  overallScore: RangeFilter;
  step1Score: RangeFilter;
  step2Score: RangeFilter;
  step4Score: RangeFilter;
  step5Score: RangeFilter;
  marketCap: RangeFilter;
  peRatio: RangeFilter;
  beta: RangeFilter;
  // Empty array means "no filter applied" (every sector/type passes) --
  // NOT "exclude everything".
  sectors: string[];
  companyTypes: string[];
}

export const DEFAULT_FILTER_STATE: ScreenerFilterState = {
  overallScore: EMPTY_RANGE,
  step1Score: EMPTY_RANGE,
  step2Score: EMPTY_RANGE,
  step4Score: EMPTY_RANGE,
  step5Score: EMPTY_RANGE,
  marketCap: EMPTY_RANGE,
  peRatio: EMPTY_RANGE,
  beta: EMPTY_RANGE,
  sectors: [],
  companyTypes: [],
};

// A range filter is only "active" if min or max is actually set -- an
// active filter can never be satisfied by a null value (e.g. filtering
// "Overall score > 70" must exclude an Incomplete ticker with no Overall
// score at all, not treat the missing value as passing).
function inRange(value: number | null, range: RangeFilter): boolean {
  if (range.min == null && range.max == null) return true;
  if (value == null) return false;
  if (range.min != null && value < range.min) return false;
  if (range.max != null && value > range.max) return false;
  return true;
}

export function filterTickerScores(rows: TickerScoreOut[], filters: ScreenerFilterState): TickerScoreOut[] {
  return rows.filter((row) => {
    if (!inRange(row.overall_score, filters.overallScore)) return false;
    if (!inRange(row.step1_score, filters.step1Score)) return false;
    if (!inRange(row.step2_score, filters.step2Score)) return false;
    if (!inRange(row.step4_score, filters.step4Score)) return false;
    if (!inRange(row.step5_score, filters.step5Score)) return false;
    if (!inRange(row.market_cap, filters.marketCap)) return false;
    if (!inRange(row.pe_ratio, filters.peRatio)) return false;
    if (!inRange(row.beta, filters.beta)) return false;
    if (filters.sectors.length > 0 && (!row.sector || !filters.sectors.includes(row.sector))) return false;
    if (filters.companyTypes.length > 0 && (!row.company_type || !filters.companyTypes.includes(row.company_type))) {
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
  | "market_cap"
  | "pe_ratio"
  | "beta";

export type SortDirection = "asc" | "desc";

export function sortTickerScores(rows: TickerScoreOut[], field: SortField, direction: SortDirection): TickerScoreOut[] {
  const dir = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[field];
    const bv = b[field];
    // Nulls always sort to the end, regardless of direction -- an
    // Incomplete ticker shouldn't jump to the top just because "asc" was
    // picked and null sorts low by default in a naive comparator.
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
