"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import { Checkbox } from "@/components/ui/checkbox";
import { RangeField } from "@/components/ui/range-field";
import {
  countActiveFilters,
  TECHNICAL_FILTER_KEYS,
  VS_SPY_FILTER_OPTIONS,
  WARREN_SIGNAL_KIND_FILTER_OPTIONS,
  WEINSTEIN_STAGE_FILTER_OPTIONS,
  type ScreenerFilterState,
} from "@/lib/screenerFilters";

interface Props {
  filters: ScreenerFilterState;
  onFiltersChange: (filters: ScreenerFilterState) => void;
}

export function TechnicalFilters({ filters, onFiltersChange }: Props) {
  function patch(partial: Partial<ScreenerFilterState>) {
    onFiltersChange({ ...filters, ...partial });
  }

  return (
    <CollapsibleFilterSection title="Technical" count={countActiveFilters(filters, false, TECHNICAL_FILTER_KEYS)}>
      <div className="space-y-4">
        {/* Moved here from Fundamental (2026-09 follow-up) -- Beta is a
            price-covariance statistic, not an accounting metric, the same
            "flavor" as 5Y vs SPY below. First item in this section per that
            change's own approved proposal. No unit (a ratio). */}
        <RangeField label="Beta" value={filters.beta} onChange={(r) => patch({ beta: r })} />
        <div className="flex flex-col items-stretch gap-2 border-t border-border-subtle pt-3">
          <MultiSelectDropdown
            label="5Y vs SPY"
            options={VS_SPY_FILTER_OPTIONS}
            selected={filters.vsSpy}
            onChange={(s) => patch({ vsSpy: s })}
          />
          <MultiSelectDropdown
            label="Weinstein stage"
            options={WEINSTEIN_STAGE_FILTER_OPTIONS}
            selected={filters.weinsteinStages}
            onChange={(s) => patch({ weinsteinStages: s })}
          />
          <MultiSelectDropdown
            label="Warren entry (2h)"
            options={WARREN_SIGNAL_KIND_FILTER_OPTIONS}
            selected={filters.warrenSignalKinds}
            onChange={(s) => patch({ warrenSignalKinds: s })}
          />
          <Checkbox
            variant="chip"
            label="BB + RSI entry (2h)"
            className="w-full"
            checked={filters.bbRsiEntrySignal}
            onChange={(e) => patch({ bbRsiEntrySignal: e.target.checked })}
          />
          <p className="text-xs text-text-tertiary">
            BB + RSI entry and Warren entry only ever match tickers on a watchlist named W1 through W5.
          </p>
        </div>
      </div>
    </CollapsibleFilterSection>
  );
}
