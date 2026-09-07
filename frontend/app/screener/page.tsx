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

  const [filters, setFilters] = useState<ScreenerFilterState>(DEFAULT_FILTER_STATE);
  const [sortField, setSortField] = useState<SortField>("overall_score");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [page, setPage] = useState(1);

  function handleUniverseChange(next: ScreenerUniverse) {
    setUniverse(next);
    setPage(1);
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
    // saved.filters_json is stored verbatim and its shape grows over time
    // (see SavedScreenerFilter's docstring) -- a filter saved before a new
    // field (e.g. vsSpy, speculativeGrowth) existed won't have that key, so
    // merge onto the defaults rather than trusting the saved object's shape.
    setFilters({ ...DEFAULT_FILTER_STATE, ...saved.filters });
    setSortField(saved.sort_field);
    setSortDirection(saved.sort_direction);
    setUniverse(saved.universe);
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
            {data.length} of {meta ? meta.total_constituents : "…"} {UNIVERSE_LABELS[universe]} tickers
            {sorted.length !== data.length && ` — ${sorted.length} match the current filters`}
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

      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="w-full shrink-0 space-y-4 lg:w-64">
          <FundamentalFilters filters={filters} onFiltersChange={handleFiltersChange} sectors={sectors} companyTypes={companyTypes} />
          <TechnicalFilters filters={filters} onFiltersChange={handleFiltersChange} />
          <SavedFiltersBar
            layout="vertical"
            universe={universe}
            sortField={sortField}
            sortDirection={sortDirection}
            filters={filters}
            onLoad={handleLoadSavedFilter}
            onReset={handleResetFilters}
          />
        </aside>

        <div className="min-w-0 flex-1 space-y-4">
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
