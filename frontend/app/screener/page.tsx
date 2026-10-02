"use client";

import { useMemo, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Pagination } from "@/components/screener/Pagination";
import { RecomputeButton } from "@/components/screener/RecomputeButton";
import { SavedFiltersBar } from "@/components/screener/SavedFiltersBar";
import { ScreenerCard } from "@/components/screener/ScreenerCard";
import { SortControls } from "@/components/screener/SortControls";
import { FundamentalFilters } from "@/components/screener/FundamentalFilters";
import { TechnicalFilters } from "@/components/screener/TechnicalFilters";
import { UniverseSelector } from "@/components/screener/UniverseSelector";
import { WatchlistFilters } from "@/components/screener/WatchlistFilters";
import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import { PageHeader } from "@/components/ui/page-header";
import type { SavedScreenerFilter, ScreenerUniverse } from "@/lib/api/types";
import { useScreener, useScreenerMeta } from "@/lib/hooks/useScreener";
import { useWatchlists } from "@/lib/hooks/useWatchlists";
import {
  DEFAULT_FILTER_STATE,
  excludeEtfs,
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
  nasdaq: "Nasdaq",
  dow: "Dow 30",
  all: "All",
};

// What the sort is on first load, and what Reset puts it back to.
const DEFAULT_SORT_FIELD: SortField = "overall_score";
const DEFAULT_SORT_DIRECTION: SortDirection = "desc";

const NO_OPTIONS = { sectors: [] as string[], companyTypes: [] as string[] };

export default function ScreenerPage() {
  const [universe, setUniverse] = useState<ScreenerUniverse>("all");
  const { data: rawData, error } = useScreener(universe);
  // Stock equities only -- ETFs are dropped here, before counts/dropdown
  // options/filters all derive from `data` (see screenerFilters.ts::excludeEtfs).
  const data = useMemo(() => (rawData ? excludeEtfs(rawData) : undefined), [rawData]);
  const { data: meta } = useScreenerMeta(universe);
  const { data: watchlists } = useWatchlists();

  const [filters, setFilters] = useState<ScreenerFilterState>(DEFAULT_FILTER_STATE);
  const [sortField, setSortField] = useState<SortField>(DEFAULT_SORT_FIELD);
  const [sortDirection, setSortDirection] = useState<SortDirection>(DEFAULT_SORT_DIRECTION);
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

  // The Sector and Company type options are read off the loaded rows. While a
  // new universe loads there are no rows, so keep the last known lists rather
  // than emptying the two multi-selects (the sidebar stays mounted; see below).
  const loadedOptions = useMemo(
    () => (data ? { sectors: extractSectors(data), companyTypes: extractCompanyTypes(data) } : null),
    [data]
  );
  const [knownOptions, setKnownOptions] = useState(loadedOptions);
  if (loadedOptions && loadedOptions !== knownOptions) setKnownOptions(loadedOptions);
  const { sectors, companyTypes } = loadedOptions ?? knownOptions ?? NO_OPTIONS;

  const filtered = useMemo(
    () => filterTickerScores(data ?? [], filters, watchlistTickerSet),
    [data, filters, watchlistTickerSet]
  );
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
    // ...and back to the page's default sort as well.
    setSortField(DEFAULT_SORT_FIELD);
    setSortDirection(DEFAULT_SORT_DIRECTION);
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

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader
        title="Screener"
        subtitle={
          !data ? undefined : watchlistActive && selectedWatchlist ? (
            <>
              {watchlistScoredCount} of {selectedWatchlist.tickers.length} &quot;{selectedWatchlist.name}&quot; tickers
              {sorted.length !== watchlistScoredCount && ` — ${sorted.length} match the current filters`}
            </>
          ) : (
            <>
              {data.length} of {meta ? meta.total_constituents : "…"} {UNIVERSE_LABELS[universe]} tickers
              {sorted.length !== data.length && ` — ${sorted.length} match the current filters`}
              {meta && meta.hidden_inactive > 0 && ` · ${meta.hidden_inactive} not viewed in 30 days are hidden`}
            </>
          )
        }
        actions={
          <>
            <UniverseSelector value={universe} onChange={handleUniverseChange} />
            <RecomputeButton />
            <AddToWatchlistButton
              tickers={sorted.map((row) => row.ticker)}
              label="Add to watchlist"
              confirmDescription={`all ${sorted.length} filtered tickers`}
              disabled={sorted.length === 0}
            />
          </>
        }
      />

      <SortControls sortField={sortField} sortDirection={sortDirection} onChange={handleSortChange} />

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
          {/* Loading and error live here, not in place of the page: the header, the
              Sort row and the sidebar (collapse state, the active saved-view name,
              a half-typed view name, range drafts) stay mounted across a universe
              switch. */}
          {error ? (
            <p className="py-12 text-sm text-negative">Failed to load the Screener.</p>
          ) : !data ? (
            <p className="py-12 text-sm text-text-tertiary animate-pulse">Loading Screener…</p>
          ) : (
            <>
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
            </>
          )}
        </div>
      </div>
    </PageContainer>
  );
}
