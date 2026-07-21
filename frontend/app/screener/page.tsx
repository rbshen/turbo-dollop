"use client";

import { useMemo, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { Pagination } from "@/components/screener/Pagination";
import { RecomputeButton } from "@/components/screener/RecomputeButton";
import { ScreenerCard } from "@/components/screener/ScreenerCard";
import { ScreenerFilters } from "@/components/screener/ScreenerFilters";
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

export default function ScreenerPage() {
  const { data, error } = useScreener();
  const { data: meta } = useScreenerMeta();

  const [filters, setFilters] = useState<ScreenerFilterState>(DEFAULT_FILTER_STATE);
  const [sortField, setSortField] = useState<SortField>("overall_score");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [page, setPage] = useState(1);

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

  function handleSortChange(field: SortField, direction: SortDirection) {
    setSortField(field);
    setSortDirection(direction);
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
          <h1 className="text-xl font-semibold text-zinc-100">Screener</h1>
          <p className="text-xs text-zinc-500">
            {data.length} of {meta ? meta.total_sp500_constituents : "…"} S&P 500 tickers
            {sorted.length !== data.length && ` — ${sorted.length} match the current filters`}
          </p>
        </div>
        <RecomputeButton />
      </div>

      <ScreenerFilters
        filters={filters}
        onFiltersChange={handleFiltersChange}
        sectors={sectors}
        companyTypes={companyTypes}
        sortField={sortField}
        sortDirection={sortDirection}
        onSortChange={handleSortChange}
      />

      {sorted.length === 0 ? (
        <p className="py-12 text-center text-sm text-zinc-600">No tickers match the current filters.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {pageRows.map((row) => (
            <ScreenerCard key={row.ticker} data={row} />
          ))}
        </div>
      )}

      <Pagination page={currentPage} nPages={nPages} onPage={setPage} />
    </PageContainer>
  );
}
