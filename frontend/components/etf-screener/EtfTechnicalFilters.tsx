"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import { Checkbox } from "@/components/ui/checkbox";
import { RangeField } from "@/components/ui/range-field";
import {
  countActiveEtfFilters,
  ETF_TECHNICAL_FILTER_KEYS,
  type EtfFilterState,
} from "@/lib/etfScreenerFilters";
import { MONITORED_WATCHLISTS_PHRASE } from "@/lib/monitoredWatchlists";
import { WARREN_SIGNAL_KIND_FILTER_OPTIONS, WEINSTEIN_STAGE_FILTER_OPTIONS } from "@/lib/screenerFilters";

interface Props {
  filters: EtfFilterState;
  onFiltersChange: (filters: EtfFilterState) => void;
}

// The ETFs page's twin of TechnicalFilters: Beta first, then 1Y vs SPY (a range in percentage points here; the Stocks
// page's 5Y vs SPY is an Outperform/Underperform bucket), then the same Weinstein / Warren / BB+RSI controls and option
// lists. Beta is null for a non-equity fund (the backend's rule), so an active Beta range drops those rows.
export function EtfTechnicalFilters({ filters, onFiltersChange }: Props) {
  function patch(partial: Partial<EtfFilterState>) {
    onFiltersChange({ ...filters, ...partial });
  }

  return (
    <CollapsibleFilterSection title="Technical" count={countActiveEtfFilters(filters, ETF_TECHNICAL_FILTER_KEYS)}>
      <div className="space-y-4">
        <RangeField label="Beta" value={filters.beta} onChange={(r) => patch({ beta: r })} />
        <RangeField label="1Y vs SPY" unit="pp" value={filters.vsSpy1y} onChange={(r) => patch({ vsSpy1y: r })} />
        <div className="flex flex-col items-stretch gap-2 border-t border-border-subtle pt-3">
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
            BB + RSI entry and Warren entry only ever match ETFs on {MONITORED_WATCHLISTS_PHRASE}.
          </p>
        </div>
      </div>
    </CollapsibleFilterSection>
  );
}
