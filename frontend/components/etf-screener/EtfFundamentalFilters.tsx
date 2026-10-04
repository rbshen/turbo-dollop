"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import { RangeField } from "@/components/ui/range-field";
import {
  countActiveEtfFilters,
  ETF_FUNDAMENTAL_FILTER_KEYS,
  type EtfFilterState,
} from "@/lib/etfScreenerFilters";
import { MARKET_CAP_SUFFIXES } from "@/lib/screenerFilters";

interface Props {
  filters: EtfFilterState;
  onFiltersChange: (filters: EtfFilterState) => void;
  assetClasses: string[];
}

// The ETFs page's twin of FundamentalFilters (its fields are a different set, on a different state type; the
// primitives are the same). An ETF has no accounting figures, so "Fundamental" here means the fund's own facts and its
// quote: asset class, expense ratio, Quote (the price, as on the Stocks page, plus the 1-day change) and AUM.
export function EtfFundamentalFilters({ filters, onFiltersChange, assetClasses }: Props) {
  function patch(partial: Partial<EtfFilterState>) {
    onFiltersChange({ ...filters, ...partial });
  }

  return (
    <CollapsibleFilterSection title="Fundamental" count={countActiveEtfFilters(filters, ETF_FUNDAMENTAL_FILTER_KEYS)}>
      <div className="space-y-4">
        <MultiSelectDropdown
          label="Asset class"
          options={assetClasses.map((c) => ({ value: c, label: c }))}
          selected={filters.assetClasses}
          onChange={(s) => patch({ assetClasses: s })}
        />
        <div className="grid grid-cols-1 gap-y-3 border-t border-border-subtle pt-3">
          <RangeField label="Expense ratio" unit="%" value={filters.expenseRatio} onChange={(r) => patch({ expenseRatio: r })} />
          <RangeField label="Quote" unit="USD" value={filters.quote} onChange={(r) => patch({ quote: r })} />
          <RangeField label="1D change" unit="%" value={filters.change1d} onChange={(r) => patch({ change1d: r })} />
          <RangeField
            label="AUM"
            unit="USD"
            hint="Type 500M or 2B."
            suffixes={MARKET_CAP_SUFFIXES}
            min={0}
            value={filters.aum}
            onChange={(r) => patch({ aum: r })}
          />
        </div>
      </div>
    </CollapsibleFilterSection>
  );
}
