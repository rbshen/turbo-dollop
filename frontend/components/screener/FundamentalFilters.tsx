"use client";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import { Checkbox } from "@/components/ui/checkbox";
import { RangeField } from "@/components/ui/range-field";
import {
  countActiveFilters,
  FUNDAMENTAL_FILTER_KEYS,
  MARKET_CAP_SUFFIXES,
  MOAT_FILTER_OPTIONS,
  VALUATION_FILTER_OPTIONS,
  type ScreenerFilterState,
} from "@/lib/screenerFilters";

interface Props {
  filters: ScreenerFilterState;
  onFiltersChange: (filters: ScreenerFilterState) => void;
  sectors: string[];
  companyTypes: string[];
}

export function FundamentalFilters({ filters, onFiltersChange, sectors, companyTypes }: Props) {
  // Each RangeField hands back the exact { min, max } object it emitted and gets
  // it back unchanged through `filters`: RangeField reads a different object as
  // an external change (Reset, a loaded saved view) and re-syncs its boxes.
  function patch(partial: Partial<ScreenerFilterState>) {
    onFiltersChange({ ...filters, ...partial });
  }

  return (
    <CollapsibleFilterSection title="Fundamental" count={countActiveFilters(filters, false, FUNDAMENTAL_FILTER_KEYS)}>
      <div className="space-y-4">
        {/* 9 Min/Max range filters in the design handoff's original order minus
            Beta (moved to Technical, 2026-09 follow-up -- a price-covariance
            statistic, not an accounting metric, same reasoning that already put
            5Y vs SPY under Technical), plus Quote (2026-09-15, a raw price figure
            in the same family as Market Cap, so placed just before it): Overall,
            Financials, Growth rate, Profitability, Debt, Quote, Mkt cap, P/E,
            Growth -- one flat column, in a ~256px sidebar. Units sit in each
            label row: every Quote and Mkt cap is USD (every ticker quotes in
            USD), P/E is a multiple ("x"), Growth is a percent; the score fields
            have none. */}
        <div className="grid grid-cols-1 gap-y-3">
          <RangeField label="Overall" value={filters.overallScore} onChange={(r) => patch({ overallScore: r })} />
          <RangeField label="Financials" value={filters.step1Score} onChange={(r) => patch({ step1Score: r })} />
          <RangeField label="Growth rate" value={filters.step2Score} onChange={(r) => patch({ step2Score: r })} />
          <RangeField label="Profitability" value={filters.step4Score} onChange={(r) => patch({ step4Score: r })} />
          <RangeField label="Debt" value={filters.step5Score} onChange={(r) => patch({ step5Score: r })} />
          <RangeField label="Quote" unit="USD" value={filters.quote} onChange={(r) => patch({ quote: r })} />
          <RangeField
            label="Mkt cap"
            unit="USD"
            hint="Type 500M or 2B."
            suffixes={MARKET_CAP_SUFFIXES}
            min={0}
            value={filters.marketCap}
            onChange={(r) => patch({ marketCap: r })}
          />
          <RangeField label="P/E" unit="x" value={filters.peRatio} onChange={(r) => patch({ peRatio: r })} />
          <RangeField label="Growth" unit="%" value={filters.growthRate} onChange={(r) => patch({ growthRate: r })} />
        </div>

        <div className="flex flex-col items-stretch gap-2 border-t border-border-subtle pt-3">
          <MultiSelectDropdown
            label="Sector"
            options={sectors.map((s) => ({ value: s, label: s }))}
            selected={filters.sectors}
            onChange={(s) => patch({ sectors: s })}
          />
          <MultiSelectDropdown
            label="Company type"
            options={companyTypes.map((t) => ({ value: t, label: t }))}
            selected={filters.companyTypes}
            onChange={(s) => patch({ companyTypes: s })}
          />
          <MultiSelectDropdown label="Moat" options={MOAT_FILTER_OPTIONS} selected={filters.moat} onChange={(s) => patch({ moat: s })} />
          <MultiSelectDropdown
            label="Valuation"
            options={VALUATION_FILTER_OPTIONS}
            selected={filters.valuationVerdict}
            onChange={(s) => patch({ valuationVerdict: s })}
          />
          {/* A chip: the checked fill is the applied signal, not orange. */}
          <Checkbox
            variant="chip"
            label="Speculative growth"
            className="w-full"
            checked={filters.speculativeGrowth}
            onChange={(e) => patch({ speculativeGrowth: e.target.checked })}
          />
        </div>
      </div>
    </CollapsibleFilterSection>
  );
}
