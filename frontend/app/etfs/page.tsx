"use client";

import { useMemo, useState } from "react";

import { EtfFundamentalFilters } from "@/components/etf-screener/EtfFundamentalFilters";
import { EtfScreenerCard } from "@/components/etf-screener/EtfScreenerCard";
import { EtfTechnicalFilters } from "@/components/etf-screener/EtfTechnicalFilters";
import { SavedEtfFiltersBar } from "@/components/etf-screener/SavedEtfFiltersBar";
import { PageContainer } from "@/components/layout/PageContainer";
import { Pagination } from "@/components/screener/Pagination";
import { SortControls } from "@/components/screener/SortControls";
import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import { PageHeader } from "@/components/ui/page-header";
import type { SavedEtfFilter } from "@/lib/api/types";
import {
  DEFAULT_ETF_FILTER_STATE,
  DEFAULT_ETF_SORT_DIRECTION,
  DEFAULT_ETF_SORT_FIELD,
  ETF_SORT_OPTIONS,
  filterEtfRows,
  sortEtfRows,
  type EtfFilterState,
  type EtfSortField,
} from "@/lib/etfScreenerFilters";
import { useEtfScreener, useEtfScreenerMeta } from "@/lib/hooks/useEtfScreener";
import type { SortDirection } from "@/lib/screenerFilters";

// Same page size as the Stocks Screener (6 rows of cards at the 3-column xl grid).
const PAGE_SIZE = 18;

const NO_ASSET_CLASSES: string[] = [];

// The ETFs page: the Stocks Screener's shell (header, sort row, sidebar + card grid, pagination, saved views) over the
// ETF read-model (GET /api/etf-screener). Filtering, sorting and paging are client-side, as on the Stocks page. One
// universe, so no universe selector, no Watchlist filter (the only ETF list is the ETF-only "ETF" watchlist, which is
// managed on the Watchlists page), and no Recompute: the rows are written by the nightly ETF job. Spec:
// docs/specs/etf-screener.md.
export default function EtfsPage() {
  const { data, error } = useEtfScreener();
  const { data: meta } = useEtfScreenerMeta();

  const [filters, setFilters] = useState<EtfFilterState>(DEFAULT_ETF_FILTER_STATE);
  const [sortField, setSortField] = useState<EtfSortField>(DEFAULT_ETF_SORT_FIELD);
  const [sortDirection, setSortDirection] = useState<SortDirection>(DEFAULT_ETF_SORT_DIRECTION);
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => filterEtfRows(data ?? [], filters), [data, filters]);
  const sorted = useMemo(() => sortEtfRows(filtered, sortField, sortDirection), [filtered, sortField, sortDirection]);

  const nPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const currentPage = Math.min(page, nPages);
  const pageRows = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  function handleFiltersChange(next: EtfFilterState) {
    setFilters(next);
    setPage(1);
  }

  function handleResetFilters() {
    handleFiltersChange(DEFAULT_ETF_FILTER_STATE);
    setSortField(DEFAULT_ETF_SORT_FIELD);
    setSortDirection(DEFAULT_ETF_SORT_DIRECTION);
  }

  function handleSortChange(field: EtfSortField, direction: SortDirection) {
    setSortField(field);
    setSortDirection(direction);
    setPage(1);
  }

  function handleLoadSavedFilter(saved: SavedEtfFilter) {
    // filters_json is stored verbatim and its shape grows over time: merge onto the defaults rather than trusting it.
    setFilters({ ...DEFAULT_ETF_FILTER_STATE, ...saved.filters });
    setSortField(saved.sort_field);
    setSortDirection(saved.sort_direction);
    // saved.watchlist_id is ignored: the ETFs page has no Watchlist filter (a view saved before it was removed loads
    // as the same view without the watchlist scope).
    setPage(1);
  }

  // The table is empty until the nightly ETF job has run: say so, rather than showing a blank grid.
  const tableEmpty = data != null && data.length === 0;

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader
        title="ETFs"
        subtitle={
          !data ? undefined : (
            <>
              {data.length} of {meta ? meta.total_etfs : "…"} ETFs
              {sorted.length !== data.length && ` — ${sorted.length} match the current filters`}
            </>
          )
        }
        actions={
          <AddToWatchlistButton
            tickers={sorted.map((row) => row.ticker)}
            label="Add to watchlist"
            confirmDescription={`all ${sorted.length} filtered tickers`}
            disabled={sorted.length === 0}
            audience="etf"
          />
        }
      />

      <SortControls sortField={sortField} sortDirection={sortDirection} onChange={handleSortChange} options={ETF_SORT_OPTIONS} />

      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="w-full shrink-0 space-y-4 lg:w-64">
          <EtfFundamentalFilters
            filters={filters}
            onFiltersChange={handleFiltersChange}
            assetClasses={meta?.asset_classes ?? NO_ASSET_CLASSES}
          />
          <EtfTechnicalFilters filters={filters} onFiltersChange={handleFiltersChange} />
          <SavedEtfFiltersBar
            sortField={sortField}
            sortDirection={sortDirection}
            filters={filters}
            onLoad={handleLoadSavedFilter}
            onReset={handleResetFilters}
          />
        </aside>

        <div className="min-w-0 flex-1 space-y-4">
          {error ? (
            <p className="py-12 text-sm text-negative">Failed to load the ETFs.</p>
          ) : !data ? (
            <p className="py-12 text-sm text-text-tertiary animate-pulse">Loading ETFs…</p>
          ) : (
            <>
              {tableEmpty ? (
                <p className="py-12 text-center text-sm text-text-tertiary">
                  ETF data hasn&apos;t been loaded yet. It is filled by the nightly ETF job.
                </p>
              ) : sorted.length === 0 ? (
                <p className="py-12 text-center text-sm text-text-tertiary">No ETFs match the current filters.</p>
              ) : (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {pageRows.map((row) => (
                    <EtfScreenerCard key={row.ticker} data={row} />
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
