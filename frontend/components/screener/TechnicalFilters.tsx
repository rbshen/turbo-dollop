"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import {
  PULLBACK_STATUS_FILTER_OPTIONS,
  REVERSAL_STATUS_FILTER_OPTIONS,
  VS_SPY_FILTER_OPTIONS,
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
    <CollapsibleFilterSection title="Technical">
      <div className="flex flex-col items-stretch gap-2">
        <MultiSelectDropdown
          label="5Y vs SPY"
          options={VS_SPY_FILTER_OPTIONS}
          selected={filters.vsSpy}
          onChange={(s) => patch({ vsSpy: s })}
        />
        <MultiSelectDropdown
          label="Weinstein Stage"
          options={WEINSTEIN_STAGE_FILTER_OPTIONS}
          selected={filters.weinsteinStages}
          onChange={(s) => patch({ weinsteinStages: s })}
        />
        <MultiSelectDropdown
          label="Reversal"
          options={REVERSAL_STATUS_FILTER_OPTIONS}
          selected={filters.reversalStatuses}
          onChange={(s) => patch({ reversalStatuses: s })}
        />
        <MultiSelectDropdown
          label="Pullback"
          options={PULLBACK_STATUS_FILTER_OPTIONS}
          selected={filters.pullbackStatuses}
          onChange={(s) => patch({ pullbackStatuses: s })}
        />
      </div>
    </CollapsibleFilterSection>
  );
}
