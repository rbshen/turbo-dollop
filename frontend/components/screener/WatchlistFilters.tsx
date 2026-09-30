"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { FormField } from "@/components/ui/form-field";
import { Select } from "@/components/ui/Select";
import type { WatchlistOut } from "@/lib/api/types";
import { countActiveFilters, DEFAULT_FILTER_STATE } from "@/lib/screenerFilters";

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
//
// The section is already titled "Watchlist", so the field's own label is
// "Limit results to" (a second "Watchlist" would read as a duplicate). The
// filter is IN EFFECT only while a watchlist is selected and the universe is
// All; a selection that is dimmed because the universe isn't All is not
// applied, so its label is not orange and the section badge does not count it.
export function WatchlistFilters({ watchlists, value, onChange, disabled }: Props) {
  const inEffect = value != null && !disabled;

  return (
    <CollapsibleFilterSection title="Watchlist" count={countActiveFilters(DEFAULT_FILTER_STATE, inEffect, [])}>
      <FormField
        label="Limit results to"
        htmlFor="screener-watchlist"
        density="compact"
        applied={inEffect}
        disabled={disabled}
        hint={
          disabled
            ? 'Only applies when the universe toggle above is set to "All."'
            : "Scopes every Fundamental and Technical filter to this watchlist's tickers."
        }
      >
        <Select
          id="screener-watchlist"
          size="full"
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        >
          <option value="">None</option>
          {(watchlists ?? []).map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
      </FormField>
    </CollapsibleFilterSection>
  );
}
