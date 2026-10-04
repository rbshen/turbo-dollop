"use client";

import { SavedFiltersBarView } from "@/components/screener/SavedFiltersBar";
import type { SavedEtfFilter } from "@/lib/api/types";
import type { EtfFilterState, EtfSortField } from "@/lib/etfScreenerFilters";
import { deleteEtfFilter, saveEtfFilter, useSavedEtfFilters } from "@/lib/hooks/useSavedEtfFilters";
import type { SortDirection } from "@/lib/screenerFilters";

interface Props {
  sortField: EtfSortField;
  sortDirection: SortDirection;
  filters: EtfFilterState;
  onLoad: (saved: SavedEtfFilter) => void;
  onReset: () => void;
}

// The ETFs page's saved-views bar: the Stocks page's SavedFiltersBarView (all of the UI) wired to the `kind=etf` views.
// An ETF view has one universe, so the stock page's universe column is always "all", and no Watchlist filter, so
// `watchlist_id` is always saved as null (an older view that carries one loads with it ignored).
export function SavedEtfFiltersBar(props: Props) {
  const { data: saved } = useSavedEtfFilters();
  return (
    <SavedFiltersBarView<"all", EtfSortField, EtfFilterState, SavedEtfFilter>
      {...props}
      universe="all"
      watchlistId={null}
      saved={saved}
      onSave={saveEtfFilter}
      onDelete={deleteEtfFilter}
    />
  );
}
