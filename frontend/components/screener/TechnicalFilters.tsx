"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import { VS_SPY_FILTER_OPTIONS, WEINSTEIN_STAGE_FILTER_OPTIONS, type ScreenerFilterState } from "@/lib/screenerFilters";

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
      </div>
    </CollapsibleFilterSection>
  );
}
