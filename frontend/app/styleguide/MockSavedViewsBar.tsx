"use client";

// The real saved-views bar (SavedFiltersBarView) over an in-memory list, for the
// styleguide mocks: Save adds a view, Delete removes one, both after a short fake
// delay so the Saving… state is visible. Nothing here can reach the backend.
import { useState } from "react";

import { SavedFiltersBarView, type SaveStep } from "@/components/screener/SavedFiltersBar";
import type { SavedScreenerFilter } from "@/lib/api/types";
import { DEFAULT_FILTER_STATE, type ScreenerFilterState } from "@/lib/screenerFilters";

function mockView(id: number, name: string): SavedScreenerFilter {
  return {
    id,
    name,
    universe: "all",
    sort_field: "overall_score",
    sort_direction: "desc",
    filters: DEFAULT_FILTER_STATE,
    watchlist_id: null,
    created_at: "",
    updated_at: "",
  } as SavedScreenerFilter;
}

export const MOCK_VIEWS: SavedScreenerFilter[] = [
  mockView(1, "Quality compounders"),
  mockView(2, "Cheap with low debt"),
  mockView(3, "Stage 2 breakouts"),
  mockView(4, "A deliberately long view name that has to truncate in the list"),
];

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface MockSavedViewsBarProps {
  filters?: ScreenerFilterState;
  onReset?: () => void;
  defaultListOpen?: boolean;
  defaultSaveStep?: SaveStep;
  defaultName?: string;
  defaultActiveName?: string | null;
}

export function MockSavedViewsBar({ filters = DEFAULT_FILTER_STATE, onReset = () => {}, ...initial }: MockSavedViewsBarProps) {
  const [saved, setSaved] = useState(MOCK_VIEWS);
  return (
    <SavedFiltersBarView
      universe="all"
      sortField="overall_score"
      sortDirection="desc"
      filters={filters}
      watchlistId={null}
      onLoad={() => {}}
      onReset={onReset}
      saved={saved}
      onSave={async (name) => {
        await wait(500);
        setSaved((prev) => (prev.some((v) => v.name === name) ? prev : [...prev, mockView(Date.now(), name)]));
      }}
      onDelete={async (name) => {
        await wait(300);
        setSaved((prev) => prev.filter((v) => v.name !== name));
      }}
      {...initial}
    />
  );
}
