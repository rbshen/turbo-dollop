"use client";

import { useMemo, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Pagination } from "@/components/screener/Pagination";
import { RecomputeButton } from "@/components/screener/RecomputeButton";
import { SavedFiltersBar } from "@/components/screener/SavedFiltersBar";
import { ScreenerCard } from "@/components/screener/ScreenerCard";
import { ScreenerFilters } from "@/components/screener/ScreenerFilters";
import { UniverseSelector } from "@/components/screener/UniverseSelector";
import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import type { SavedScreenerFilter, ScreenerUniverse } from "@/lib/api/types";
import { useScreener, useScreenerMeta } from "@/lib/hooks/useScreener";
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

const PAGE_SIZE = 24;
const MAX_SELECTED = 50;

const UNIVERSE_LABELS: Record<ScreenerUniverse, string> = {
  sp500: "S&P 500",
  dow: "Dow 30",
  all: "All",
};

export default function ScreenerPage() {
  const [universe, setUniverse] = useState<ScreenerUniverse>("all");
  const { data, error } = useScreener(universe);
  const { data: meta } = useScreenerMeta(universe);

  const [filters, setFilters] = useState<ScreenerFilterState>(DEFAULT_FILTER_STATE);
  const [sortField, setSortField] = useState<SortField>("overall_score");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function handleUniverseChange(next: ScreenerUniverse) {
    setUniverse(next);
    setPage(1);
  }

  function handleToggleSelected(ticker: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(ticker)) {
        next.delete(ticker);
      } else if (next.size < MAX_SELECTED) {
        next.add(ticker);
      }
      return next;
    });
  }

  const sectors = useMemo(() => extractSectors(data ?? []), [data]);
  const companyTypes = useMemo(() => extractCompanyTypes(data ?? []), [data]);

  const filtered = useMemo(() => filterTickerScores(data ?? [], filters), [data, filters]);
  const sorted = useMemo(() => sortTickerScores(filtered, sortField, sortDirection), [filtered, sortField, sortDirection]);

  const nPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const currentPage = Math.min(page, nPages);
  const pageRows = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  function handleFiltersChange(next: ScreenerFilterState) {
    setFilters(next);
    setPage(1);
  }

  function handleResetFilters() {
    handleFiltersChange(DEFAULT_FILTER_STATE);
  }

  function handleSortChange(field: SortField, direction: SortDirection) {
    setSortField(field);
    setSortDirection(direction);
    setPage(1);
  }

  function handleLoadSavedFilter(saved: SavedScreenerFilter) {
    setFilters(saved.filters);
    setSortField(saved.sort_field);
    setSortDirection(saved.sort_direction);
    setUniverse(saved.universe);
    setPage(1);
  }

  if (error) {
    return (
      <PageContainer className="py-12">
        <p className="text-sm text-red-400">Failed to load the Screener.</p>
      </PageContainer>
    );
  }

  if (!data) {
    return (
      <PageContainer className="py-12">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Screener…</p>
      </PageContainer>
    );
  }

  return (
    <PageContainer className="space-y-6 pb-12 pt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl font-semibold text-zinc-100">Screener</h1>
          <p className="text-xs text-zinc-500">
            {data.length} of {meta ? meta.total_constituents : "…"} {UNIVERSE_LABELS[universe]} tickers
            {sorted.length !== data.length && ` — ${sorted.length} match the current filters`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <UniverseSelector value={universe} onChange={handleUniverseChange} />
          <RecomputeButton />
        </div>
      </div>

      <SavedFiltersBar
        universe={universe}
        sortField={sortField}
        sortDirection={sortDirection}
        filters={filters}
        onLoad={handleLoadSavedFilter}
        onReset={handleResetFilters}
      />

      <ScreenerFilters
        filters={filters}
        onFiltersChange={handleFiltersChange}
        sectors={sectors}
        companyTypes={companyTypes}
        sortField={sortField}
        sortDirection={sortDirection}
        onSortChange={handleSortChange}
      />

      {selected.size > 0 && (
        <div className="sticky top-12 z-20 flex flex-wrap items-center gap-3 rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm shadow-lg">
          <span className="font-medium text-zinc-200">{selected.size} selected</span>
          {selected.size >= MAX_SELECTED && (
            <span className="text-xs text-amber-400">
              {MAX_SELECTED}/{MAX_SELECTED} selected — remove one to add another
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
            >
              Clear
            </button>
            <AddToWatchlistButton tickers={Array.from(selected)} label="Add to Watchlist" />
          </div>
        </div>
      )}

      {sorted.length === 0 ? (
        <p className="py-12 text-center text-sm text-zinc-600">No tickers match the current filters.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {pageRows.map((row) => (
            <ScreenerCard
              key={row.ticker}
              data={row}
              selected={selected.has(row.ticker)}
              onToggle={handleToggleSelected}
              selectionDisabled={selected.size >= MAX_SELECTED}
            />
          ))}
        </div>
      )}

      <Pagination page={currentPage} nPages={nPages} onPage={setPage} />
    </PageContainer>
  );
}
