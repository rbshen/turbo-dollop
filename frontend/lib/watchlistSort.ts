import type { MoatValue, SortableField, WatchlistRowOut } from "@/lib/api/types";
import type { SortDirection } from "@/lib/screenerFilters";

export type { SortDirection };

export interface SortRule {
  field: SortableField;
  direction: SortDirection;
}

export const MAX_SORT_RULES = 4;

export const DEFAULT_SORT_RULES: SortRule[] = [{ field: "overall_score", direction: "desc" }];

// Every field a header can currently be clicked to sort by -- used to
// validate a rule loaded from localStorage (see app/watchlist/page.tsx)
// and to look up each field's default first-click direction below.
//
// "Trend" (the REV/NI/CFO mini-chart cluster) is deliberately NOT a
// SortableField yet. It was investigated for this redesign: the only
// candidate for a single sortable "trend slope" value is
// scoring/trend.py::classify_trend's own per-series (score: int) --
// already computed live for Revenue/Net Income/CFO on the ticker page --
// but that score is never persisted anywhere WatchlistRowOut/TickerScore
// can read it from; it only exists transiently inside a live Step1Out
// response. Sorting the Watchlist table by it would mean either a new
// per-ticker live Step 1 computation on every /rows fetch (defeats the
// page's cache-only design -- see watchlist_data.py's own docstring) or a
// new persisted column threaded through TrendAnalysis/TickerScore/nightly
// cron, and a decision about which of Revenue/Net Income/CFO (or what
// combination) it should represent. Per instruction, this is flagged as a
// follow-up rather than guessed at here -- every other column below ships
// now.
const DEFAULT_DIRECTION: Record<SortableField, SortDirection> = {
  ticker: "asc",
  sector: "asc",
  // Ordinal rank tables below are defined best-first (rank 1 = best), so
  // ascending rank order reads as "best first" -- matching the numeric
  // columns' own "most favorable first" default intent, just via rank
  // instead of raw magnitude.
  moat: "asc",
  valuation_verdict: "asc",
  consensus_rating: "asc",
  ad_divergence_swing_date: "desc",
  sma20_position_pct: "desc",
  sma50_position_pct: "desc",
  sma200_position_pct: "desc",
  market_cap: "desc",
  pe_ratio: "desc",
  beta: "desc",
  overall_score: "desc",
};

export const SORTABLE_FIELDS = Object.keys(DEFAULT_DIRECTION) as SortableField[];

export function defaultDirectionFor(field: SortableField): SortDirection {
  return DEFAULT_DIRECTION[field];
}

// Best-first ordinal ranks for the 3 non-numeric, non-text columns. A value
// missing from its map (including MoatValue/valuation_verdict's own `null`,
// and any consensus_rating string FMP hands back outside the 5 known
// tiers, e.g. "N/A") reads as Infinity below -- sorted last regardless of
// direction, mirroring the null-always-last convention every numeric/text
// field here already uses.
const MOAT_RANK: Record<MoatValue, number> = { wide_moat: 1, narrow_moat: 2, no_moat: 3 };

// Matches scoring/step3.py::classify_valuation_verdict's exact 3-value
// return set ("undervalued" | "fair" | "overvalued" | None) -- confirmed
// against the live source, not guessed from the UI labels alone.
const VALUATION_RANK: Record<string, number> = { undervalued: 1, fair: 2, overvalued: 3 };

// FMP's raw grades_consensus.consensus string (backend/data/watchlist_data.py
// ::_consensus_rating), lowercased before lookup -- same case-insensitive
// substring convention WatchlistTable.tsx's own ratingColorClass already
// uses for this exact field, since FMP's casing isn't contractually fixed.
// "N/A" (the field's own never-null placeholder, not a real rating) and any
// other unrecognized string fall through to the Infinity/sort-last case.
const RATING_RANK: Record<string, number> = {
  "strong buy": 1,
  buy: 2,
  hold: 3,
  sell: 4,
  "strong sell": 5,
};

function rank(map: Record<string, number>, value: string | null): number {
  if (value == null) return Infinity;
  return map[value.toLowerCase()] ?? Infinity;
}

// Shared by every numeric SortableField (market_cap/pe_ratio/beta/
// overall_score/sma*_position_pct) -- nulls always sort to the end
// regardless of direction, same convention screenerFilters.ts's
// sortTickerScores uses for the same reason (an Incomplete/not-yet-computed
// ticker shouldn't jump to the top just because "asc" was picked).
function compareNullable(av: number | string | null, bv: number | string | null, dir: 1 | -1): number {
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  if (typeof av === "string" || typeof bv === "string") {
    return String(av).localeCompare(String(bv)) * dir;
  }
  return (av - bv) * dir;
}

// Same null-last-regardless-of-direction convention as compareNullable
// above, generalized to a rank pair instead of raw values -- naively doing
// `(aRank - bRank) * dir` breaks this for a missing rank (Infinity): on
// "desc" (dir = -1), `(Infinity - finite) * -1` is -Infinity, which would
// sort the missing value FIRST instead of last. Handling missing ranks
// before the subtraction, exactly like compareNullable's own null checks,
// avoids that.
function compareRank(aRank: number, bRank: number, dir: 1 | -1): number {
  const aMissing = !Number.isFinite(aRank);
  const bMissing = !Number.isFinite(bRank);
  if (aMissing && bMissing) return 0;
  if (aMissing) return 1;
  if (bMissing) return -1;
  return (aRank - bRank) * dir;
}

function compareByRule(a: WatchlistRowOut, b: WatchlistRowOut, rule: SortRule): number {
  const dir = rule.direction === "asc" ? 1 : -1;
  switch (rule.field) {
    case "moat":
      return compareRank(rank(MOAT_RANK, a.moat), rank(MOAT_RANK, b.moat), dir);
    case "valuation_verdict":
      return compareRank(rank(VALUATION_RANK, a.valuation_verdict), rank(VALUATION_RANK, b.valuation_verdict), dir);
    case "consensus_rating":
      return compareRank(rank(RATING_RANK, a.consensus_rating), rank(RATING_RANK, b.consensus_rating), dir);
    default:
      return compareNullable(a[rule.field], b[rule.field], dir);
  }
}

// Generalizes screenerFilters.ts's sortTickerScores (numeric-only, single
// field) to a priority list of up to MAX_SORT_RULES rules: rows are
// compared by rules[0] first, falling through to rules[1], etc. only on a
// tie -- a standard multi-key sort. Each rule's own null-handling is
// unchanged from the old single-field sortWatchlistRows (see
// compareNullable/rank above).
export function sortWatchlistRows(rows: WatchlistRowOut[], rules: SortRule[]): WatchlistRowOut[] {
  return [...rows].sort((a, b) => {
    for (const rule of rules) {
      const cmp = compareByRule(a, b, rule);
      if (cmp !== 0) return cmp;
    }
    return 0;
  });
}

// Click-cycle for one header, per the redesign spec:
//  1. Not in `rules` -> append as lowest priority, at this field's default
//     direction (existing priorities unchanged).
//  2. Already in `rules` at its default direction (i.e. this is the 2nd
//     click) -> flip direction in place, priority position unchanged.
//  3. Already in `rules` at the flipped (non-default) direction (i.e. the
//     3rd click) -> remove it; remaining rules shift priority up.
//  4. If removal empties `rules` -> reset to DEFAULT_SORT_RULES.
//  5. Not in `rules` and `rules` is already at MAX_SORT_RULES -> no-op.
// Distinguishing click 2 (flip) from click 3 (remove) by comparing the
// rule's CURRENT direction against its own default -- rather than a
// separate click counter -- means this is stateless and idempotent no
// matter how sortRules got into its current shape (e.g. loaded fresh from
// localStorage).
export function applyHeaderClick(rules: SortRule[], field: SortableField): SortRule[] {
  const idx = rules.findIndex((r) => r.field === field);
  if (idx === -1) {
    if (rules.length >= MAX_SORT_RULES) return rules;
    return [...rules, { field, direction: defaultDirectionFor(field) }];
  }

  const current = rules[idx];
  if (current.direction === defaultDirectionFor(field)) {
    const next = [...rules];
    next[idx] = { field, direction: current.direction === "asc" ? "desc" : "asc" };
    return next;
  }

  const next = rules.filter((_, i) => i !== idx);
  return next.length > 0 ? next : DEFAULT_SORT_RULES;
}
