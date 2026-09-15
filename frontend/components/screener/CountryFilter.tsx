"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { COUNTRY_FILTER_OPTIONS, DEFAULT_SCREENER_COUNTRY, FILTER_ACTIVE_LABEL_CLASS, type ScreenerCountry } from "@/lib/screenerFilters";
import { cn } from "@/lib/utils";

interface Props {
  value: ScreenerCountry;
  onChange: (country: ScreenerCountry) => void;
  // True whenever the universe toggle isn't "All" -- both sp500/dow are
  // US-only indices, so this filter is meaningless there. Same dimmed/
  // non-clearing behavior as WatchlistFilters.tsx's own `disabled` prop --
  // the selection is kept in state, not cleared, so flipping back to "All"
  // restores it.
  disabled: boolean;
}

// Sits between WatchlistFilters and FundamentalFilters in the sidebar --
// same CollapsibleFilterSection shell and single-select shape as
// WatchlistFilters.tsx, just over the fixed 2-value US/HK set rather than
// the user's own watchlists. Restricts the Screener result set to tickers
// whose primary listing market matches the selection (see
// TickerScoreOut.country) -- unlike Watchlist, this filter has no "off"
// state: the default is "US", not "no filter applied".
export function CountryFilter({ value, onChange, disabled }: Props) {
  const active = value !== DEFAULT_SCREENER_COUNTRY;

  return (
    <CollapsibleFilterSection title="Country">
      <div className="flex flex-col items-stretch gap-2">
        <span className={cn("text-xs", active ? FILTER_ACTIVE_LABEL_CLASS : "text-text-tertiary")}>Country</span>
        <select
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value as ScreenerCountry)}
          className="h-8 rounded-md border border-border-input bg-surface px-2 text-xs text-text-primary focus:border-brand focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        >
          {COUNTRY_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-text-tertiary">
          {disabled
            ? 'Only applies when the universe toggle above is set to "All."'
            : "Restricts every result to tickers primarily listed in this market."}
        </p>
      </div>
    </CollapsibleFilterSection>
  );
}
