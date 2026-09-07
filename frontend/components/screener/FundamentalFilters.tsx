"use client";

import { useState } from "react";

import { CollapsibleFilterSection } from "@/components/screener/CollapsibleFilterSection";
import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import {
  MOAT_FILTER_OPTIONS,
  parseMarketCapInput,
  VALUATION_FILTER_OPTIONS,
  type RangeFilter,
  type ScreenerFilterState,
} from "@/lib/screenerFilters";

interface Props {
  filters: ScreenerFilterState;
  onFiltersChange: (filters: ScreenerFilterState) => void;
  sectors: string[];
  companyTypes: string[];
}

// Label stacked above a Min/Max row, each input sized via flex-1/min-w-0
// rather than a fixed width -- a fixed w-24 label + 2x w-20 inputs (the old
// single-row layout, sized for the full-width top bar this used to live in)
// overflows a ~224px sidebar column's actual content width. Stacking keeps
// this correct at any sidebar width instead of depending on a specific one.
function RangeInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: RangeFilter;
  onChange: (range: RangeFilter) => void;
}) {
  return (
    <div className="space-y-1">
      <span className="text-xs text-text-tertiary">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          placeholder="Min"
          value={value.min ?? ""}
          onChange={(e) => onChange({ ...value, min: e.target.value === "" ? null : Number(e.target.value) })}
          className="h-8 w-0 min-w-0 flex-1 rounded-md border border-border-input bg-surface px-2 text-xs text-text-primary placeholder:text-text-tertiary focus:border-brand focus:outline-none"
        />
        <span className="shrink-0 text-text-tertiary">–</span>
        <input
          type="number"
          placeholder="Max"
          value={value.max ?? ""}
          onChange={(e) => onChange({ ...value, max: e.target.value === "" ? null : Number(e.target.value) })}
          className="h-8 w-0 min-w-0 flex-1 rounded-md border border-border-input bg-surface px-2 text-xs text-text-primary placeholder:text-text-tertiary focus:border-brand focus:outline-none"
        />
      </div>
    </div>
  );
}

/** One side (min or max) of the Market Cap range: free-text so "1B" / "2 m"
 * can be typed, not just raw digits. Kept as local text state independent
 * of the numeric filter value -- an in-progress or invalid keystroke (e.g.
 * "1X") shows an inline error and leaves the last valid filter value
 * untouched, rather than being coerced to 0/NaN or clearing the filter. */
function MarketCapSideInput({
  placeholder,
  value,
  onChange,
}: {
  placeholder: string;
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  const [text, setText] = useState(value == null ? "" : String(value));
  const [invalid, setInvalid] = useState(false);

  function handleChange(next: string) {
    setText(next);
    const parsed = parseMarketCapInput(next);
    if (parsed === undefined) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    onChange(parsed);
  }

  return (
    <div className="min-w-0 flex-1">
      <input
        type="text"
        inputMode="decimal"
        placeholder={placeholder}
        value={text}
        onChange={(e) => handleChange(e.target.value)}
        className={`h-8 w-full rounded-md border bg-surface px-2 text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none ${
          invalid ? "border-negative/60 focus:border-negative" : "border-border-input focus:border-brand"
        }`}
      />
      {invalid && <span className="mt-0.5 block text-[10px] text-negative">e.g. 1B, 2 M, or 500000000</span>}
    </div>
  );
}

function MarketCapRangeInput({ value, onChange }: { value: RangeFilter; onChange: (range: RangeFilter) => void }) {
  return (
    <div className="space-y-1">
      <span className="text-xs text-text-tertiary">Mkt Cap</span>
      <div className="flex items-center gap-1.5">
        <MarketCapSideInput placeholder="Min" value={value.min} onChange={(min) => onChange({ ...value, min })} />
        <span className="shrink-0 text-text-tertiary">–</span>
        <MarketCapSideInput placeholder="Max" value={value.max} onChange={(max) => onChange({ ...value, max })} />
      </div>
    </div>
  );
}

export function FundamentalFilters({ filters, onFiltersChange, sectors, companyTypes }: Props) {
  function patch(partial: Partial<ScreenerFilterState>) {
    onFiltersChange({ ...filters, ...partial });
  }

  return (
    <CollapsibleFilterSection title="Fundamental">
      <div className="space-y-4">
        {/* 9-item Min/Max range-filter grid, in the design handoff's exact
            order: Overall, Financials, Growth Rate, Profitability, Debt, Mkt
            Cap, P/E, Beta, Growth -- one flat grid, not grouped sub-rows. A
            single grid-cols-1 column (not the old sm/lg-scaling grid) -- this
            now lives in a ~256px sidebar column, not a full-width bar, so
            there's no width at which 2-3 range inputs would ever fit side by
            side. */}
        <div className="grid grid-cols-1 gap-y-3">
          <RangeInput label="Overall" value={filters.overallScore} onChange={(r) => patch({ overallScore: r })} />
          <RangeInput label="Financials" value={filters.step1Score} onChange={(r) => patch({ step1Score: r })} />
          <RangeInput label="Growth Rate" value={filters.step2Score} onChange={(r) => patch({ step2Score: r })} />
          <RangeInput label="Profitability" value={filters.step4Score} onChange={(r) => patch({ step4Score: r })} />
          <RangeInput label="Debt" value={filters.step5Score} onChange={(r) => patch({ step5Score: r })} />
          <MarketCapRangeInput value={filters.marketCap} onChange={(r) => patch({ marketCap: r })} />
          <RangeInput label="P/E" value={filters.peRatio} onChange={(r) => patch({ peRatio: r })} />
          <RangeInput label="Beta" value={filters.beta} onChange={(r) => patch({ beta: r })} />
          <RangeInput label="Growth" value={filters.growthRate} onChange={(r) => patch({ growthRate: r })} />
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
          <label className="flex h-8 items-center gap-1.5 rounded-md border border-border-input px-2 text-xs font-medium text-text-secondary">
            <input
              type="checkbox"
              checked={filters.speculativeGrowth}
              onChange={(e) => patch({ speculativeGrowth: e.target.checked })}
              className="size-3.5 rounded-sm border-border-input accent-chart-purple"
            />
            Speculative Growth
          </label>
        </div>
      </div>
    </CollapsibleFilterSection>
  );
}
