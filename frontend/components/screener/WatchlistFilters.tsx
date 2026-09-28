"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { Field } from "@/components/ui/input";
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
  const active = value != null;

  return (
    <CollapsibleFilterSection title="Watchlist">
      <div className="flex flex-col items-stretch gap-2">
        <Field label="Watchlist" htmlFor="screener-watchlist" applied={active}>
          <select
            id="screener-watchlist"
            value={value ?? ""}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
            className="h-9 w-full rounded-md border border-border-control bg-page px-3 text-sm text-text-primary focus:border-brand focus:outline-none disabled:cursor-not-allowed disabled:opacity-45"
          >
            <option value="">None</option>
            {(watchlists ?? []).map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </Field>
        <p className="text-xs text-text-tertiary">
          {disabled
            ? 'Only applies when the universe toggle above is set to "All."'
            : "Scopes every Fundamental and Technical filter to this watchlist's tickers."}
        </p>
      </div>
    </CollapsibleFilterSection>
  );
}
