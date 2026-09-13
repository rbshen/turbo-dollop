"use client";

import { useMemo, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Pagination } from "@/components/screener/Pagination";
import { RecomputeButton } from "@/components/screener/RecomputeButton";
import { SavedFiltersBar } from "@/components/screener/SavedFiltersBar";
import { ScreenerCard } from "@/components/screener/ScreenerCard";
import { FundamentalFilters } from "@/components/screener/FundamentalFilters";
import { TechnicalFilters } from "@/components/screener/TechnicalFilters";
import { UniverseSelector } from "@/components/screener/UniverseSelector";
import { WatchlistFilters } from "@/components/screener/WatchlistFilters";
import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import type { SavedScreenerFilter, ScreenerUniverse } from "@/lib/api/types";
import { useScreener, useScreenerMeta } from "@/lib/hooks/useScreener";
import { useWatchlists } from "@/lib/hooks/useWatchlists";
import {
  DEFAULT_FILTER_STATE,
  extractCompanyTypes,
  extractSectors,
  filterTickerScores,
  sortTickerScores,
  type ScreenerFilterState,
  type SortDirection,
  type SortField,
} from "@/lib/screenerFilters";

// 6 rows of cards at the grid's 3-column (xl) breakpoint -- the primary
// desktop layout the result grid is designed around (see the grid's own
// `sm:grid-cols-2 xl:grid-cols-3` below); fewer columns at a narrower
// viewport just means more (not fewer) visual rows per page, same as before.
const PAGE_SIZE = 18;

const UNIVERSE_LABELS: Record<ScreenerUniverse, string> = {
  sp500: "S&P 500",
  dow: "Dow 30",
  all: "All",
};

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "overall_score", label: "Overall score" },
  { value: "step1_score", label: "Financials score" },
  { value: "step2_score", label: "Growth Rate score" },
  { value: "step4_score", label: "Profitability score" },
  { value: "step5_score", label: "Debt score" },
  { value: "market_cap", label: "Market cap" },
  { value: "pe_ratio", label: "P/E" },
  { value: "beta", label: "Beta" },
  { value: "growth_rate", label: "Growth rate" },
];

export default function ScreenerPage() {
  const [universe, setUniverse] = useState<ScreenerUniverse>("all");
  const { data, error } = useScreener(universe);
  const { data: meta } = useScreenerMeta(universe);
  const { data: watchlists } = useWatchlists();

  const [filters, setFilters] = useState<ScreenerFilterState>(DEFAULT_FILTER_STATE);
  const [sortField, setSortField] = useState<SortField>("overall_score");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [page, setPage] = useState(1);
  // The WATCHLIST universe filter's selection. Deliberately NOT cleared
  // when `universe` flips away from "all" -- WatchlistFilters just dims the
  // dropdown in that state, and the selection is restored the moment
  // universe flips back, since the value below only ever takes effect
  // (via watchlistTickerSet) when universe === "all" anyway.
  const [watchlistId, setWatchlistId] = useState<number | null>(null);

  const selectedWatchlist = useMemo(() => (watchlists ?? []).find((w) => w.id === watchlistId) ?? null, [watchlists, watchlistId]);
  const watchlistActive = universe === "all" && selectedWatchlist != null;
  const watchlistTickerSet = useMemo(
    () => (watchlistActive && selectedWatchlist ? new Set(selectedWatchlist.tickers.map((t) => t.ticker)) : null),
    [watchlistActive, selectedWatchlist]
  );

  function handleUniverseChange(next: ScreenerUniverse) {
    setUniverse(next);
    setPage(1);
  }

  const sectors = useMemo(() => extractSectors(data ?? []), [data]);
  const companyTypes = useMemo(() => extractCompanyTypes(data ?? []), [data]);

  const filtered = useMemo(() => filterTickerScores(data ?? [], filters, watchlistTickerSet), [data, filters, watchlistTickerSet]);
  const sorted = useMemo(() => sortTickerScores(filtered, sortField, sortDirection), [filtered, sortField, sortDirection]);

  // "X of Y" transparency, watchlist flavor: the count of `data` (the
  // fetched, unfiltered universe="all" response) that also sit in the
  // selected watchlist -- mirrors ScreenerMeta's own "X of Y" note for the
  // sp500/dow universes (some watchlist tickers have never been scored, so
  // they never got a TickerScore row and can't appear even in universe=
  // "all"), computed independently of Fundamental/Technical filters the
  // same way ScreenerMeta's total_constituents is.
  const watchlistScoredCount = useMemo(() => {
    if (!watchlistTickerSet || !data) return null;
    return data.filter((row) => watchlistTickerSet.has(row.ticker)).length;
  }, [watchlistTickerSet, data]);

  const nPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const currentPage = Math.min(page, nPages);
  const pageRows = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  function handleFiltersChange(next: ScreenerFilterState) {
    setFilters(next);
    setPage(1);
  }

  function handleResetFilters() {
    handleFiltersChange(DEFAULT_FILTER_STATE);
    // "Reset" means back to the whole universe -- clears both the sp500/
    // dow/all toggle and the watchlist selection, not just the Fundamental/
    // Technical filter blob.
    setUniverse("all");
    setWatchlistId(null);
  }

  function handleWatchlistChange(next: number | null) {
    setWatchlistId(next);
    setPage(1);
  }

  function handleSortChange(field: SortField, direction: SortDirection) {
    setSortField(field);
    setSortDirection(direction);
    setPage(1);
  }

  function handleLoadSavedFilter(saved: SavedScreenerFilter) {
    // saved.filters_json is stored verbatim and its shape grows over time
    // (see SavedScreenerFilter's docstring) -- a filter saved before a new
    // field (e.g. vsSpy, speculativeGrowth) existed won't have that key, so
    // merge onto the defaults rather than trusting the saved object's shape.
    setFilters({ ...DEFAULT_FILTER_STATE, ...saved.filters });
    setSortField(saved.sort_field);
    setSortDirection(saved.sort_direction);
    // A saved watchlist scoping only applies if that watchlist still
    // exists -- one may have been deleted since this view was saved (its
    // SavedScreenerFilter row would already be gone too in that case, via
    // the delete-watchlist cascade, but an older client cache/tab could
    // still be holding a stale reference). Fall back to no watchlist
    // selected rather than erroring or pointing at nothing.
    const referencedWatchlistStillExists = saved.watchlist_id != null && (watchlists ?? []).some((w) => w.id === saved.watchlist_id);
    if (referencedWatchlistStillExists) {
      // Watchlist scoping only ever applies under "All" -- force it here
      // rather than trusting saved.universe, which could be stale/
      // inconsistent for an old save.
      setUniverse("all");
      setWatchlistId(saved.watchlist_id);
    } else {
      setUniverse(saved.universe);
      setWatchlistId(null);
    }
    setPage(1);
  }

  if (error) {
    return (
      <PageContainer className="py-12">
        <p className="text-sm text-negative">Failed to load the Screener.</p>
      </PageContainer>
    );
  }

  if (!data) {
    return (
      <PageContainer className="py-12">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Screener…</p>
      </PageContainer>
    );
  }

  return (
    <PageContainer className="space-y-6 pb-12 pt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl font-semibold text-text-primary">Screener</h1>
          <p className="text-xs text-text-tertiary">
            {watchlistActive && selectedWatchlist ? (
              <>
                {watchlistScoredCount} of {selectedWatchlist.tickers.length} &quot;{selectedWatchlist.name}&quot; tickers
                {sorted.length !== watchlistScoredCount && ` — ${sorted.length} match the current filters`}
              </>
            ) : (
              <>
                {data.length} of {meta ? meta.total_constituents : "…"} {UNIVERSE_LABELS[universe]} tickers
                {sorted.length !== data.length && ` — ${sorted.length} match the current filters`}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <UniverseSelector value={universe} onChange={handleUniverseChange} />
          <RecomputeButton />
          <AddToWatchlistButton
            tickers={sorted.map((row) => row.ticker)}
            label="Add to Watchlist"
            confirmDescription={`all ${sorted.length} filtered tickers`}
            disabled={sorted.length === 0}
          />
        </div>
      </div>

      <div className="flex justify-end">
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Sort</span>
          <select
            value={sortField}
            onChange={(e) => handleSortChange(e.target.value as SortField, sortDirection)}
            className="h-8 rounded-md border border-border-input bg-surface px-2 text-xs text-text-primary focus:border-brand focus:outline-none"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => handleSortChange(sortField, sortDirection === "asc" ? "desc" : "asc")}
            className="inline-flex h-8 items-center rounded-md border border-border-input bg-surface px-2 text-xs text-text-secondary transition-colors hover:border-brand hover:text-text-primary"
            title={sortDirection === "asc" ? "Ascending" : "Descending"}
          >
            {sortDirection === "asc" ? "↑ Asc" : "↓ Desc"}
          </button>
        </div>
      </div>

      {/* Sidebar and main content are siblings starting at the same
          vertical position -- the sort control above is deliberately its
          own full-width row (not nested inside the main column) so the
          Fundamental card's top edge lines up with the ticker grid's top
          edge, rather than sitting a row-height higher. */}
      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="w-full shrink-0 space-y-4 lg:w-64">
          <WatchlistFilters watchlists={watchlists} value={watchlistId} onChange={handleWatchlistChange} disabled={universe !== "all"} />
          <FundamentalFilters filters={filters} onFiltersChange={handleFiltersChange} sectors={sectors} companyTypes={companyTypes} />
          <TechnicalFilters filters={filters} onFiltersChange={handleFiltersChange} />
          <SavedFiltersBar
            layout="vertical"
            universe={universe}
            sortField={sortField}
            sortDirection={sortDirection}
            filters={filters}
            watchlistId={watchlistId}
            onLoad={handleLoadSavedFilter}
            onReset={handleResetFilters}
          />
        </aside>

        <div className="min-w-0 flex-1 space-y-4">
          {sorted.length === 0 ? (
            <p className="py-12 text-center text-sm text-text-tertiary">No tickers match the current filters.</p>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {pageRows.map((row) => (
                <ScreenerCard key={row.ticker} data={row} />
              ))}
            </div>
          )}

          <Pagination page={currentPage} nPages={nPages} onPage={setPage} />
        </div>
      </div>
    </PageContainer>
  );
}
