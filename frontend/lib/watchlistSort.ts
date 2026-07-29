import type { WatchlistRowOut, WatchlistSortField } from "@/lib/api/types";
import type { SortDirection } from "@/lib/screenerFilters";

// Generalizes screenerFilters.ts's sortTickerScores (numeric-only) to also
// sort by `ticker` (a string) -- same null-last convention: nulls always
// sort to the end regardless of direction, so an Incomplete ticker doesn't
// jump to the top just because "asc" was picked.
export function sortWatchlistRows(rows: WatchlistRowOut[], field: WatchlistSortField, direction: SortDirection): WatchlistRowOut[] {
  const dir = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[field];
    const bv = b[field];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string" || typeof bv === "string") {
      return String(av).localeCompare(String(bv)) * dir;
    }
    return (av - bv) * dir;
  });
}
