"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import type { WatchlistOut } from "@/lib/api/types";

interface Props {
  watchlists: WatchlistOut[] | undefined;
  value: number | null;
  onChange: (watchlistId: number | null) => void;
  // True whenever the universe toggle isn't "All" -- the dropdown stays
  // dimmed/disabled but keeps its current selection in state (not cleared)
  // so flipping back to "All" restores it. See page.tsx's own comment on
  // why this doesn't need any state-clearing logic.
  disabled: boolean;
}

// Sits above FundamentalFilters/TechnicalFilters in the sidebar (Watchlist
// -> Fundamental -> Technical) -- same CollapsibleFilterSection shell,
// single-select dropdown rather than MultiSelectDropdown since a Screener
// result set can only be scoped to one base watchlist at a time.
export function WatchlistFilters({ watchlists, value, onChange, disabled }: Props) {
  return (
    <CollapsibleFilterSection title="Watchlist">
      <div className="flex flex-col items-stretch gap-2">
        <select
          value={value ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          className="h-8 rounded-md border border-border-input bg-surface px-2 text-xs text-text-primary focus:border-brand focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="">None</option>
          {(watchlists ?? []).map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <p className="text-xs text-text-tertiary">
          {disabled
            ? 'Only applies when the universe toggle above is set to "All."'
            : "Scopes every Fundamental and Technical filter to this watchlist's tickers."}
        </p>
      </div>
    </CollapsibleFilterSection>
  );
}
