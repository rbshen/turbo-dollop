"use client";

import { MultiSelectDropdown } from "@/components/screener/MultiSelectDropdown";
import type { RangeFilter, ScreenerFilterState, SortDirection, SortField } from "@/lib/screenerFilters";

interface Props {
  filters: ScreenerFilterState;
  onFiltersChange: (filters: ScreenerFilterState) => void;
  sectors: string[];
  companyTypes: string[];
  sortField: SortField;
  sortDirection: SortDirection;
  onSortChange: (field: SortField, direction: SortDirection) => void;
}

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "overall_score", label: "Overall score" },
  { value: "step1_score", label: "Step 1 score" },
  { value: "step2_score", label: "Step 2 score" },
  { value: "step4_score", label: "Step 4 score" },
  { value: "step5_score", label: "Step 5 score" },
  { value: "market_cap", label: "Market cap" },
  { value: "pe_ratio", label: "P/E" },
  { value: "beta", label: "Beta" },
];

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
    <div className="flex items-center gap-1.5">
      <span className="w-16 shrink-0 text-xs text-zinc-500">{label}</span>
      <input
        type="number"
        placeholder="Min"
        value={value.min ?? ""}
        onChange={(e) => onChange({ ...value, min: e.target.value === "" ? null : Number(e.target.value) })}
        className="w-20 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
      />
      <span className="text-zinc-700">–</span>
      <input
        type="number"
        placeholder="Max"
        value={value.max ?? ""}
        onChange={(e) => onChange({ ...value, max: e.target.value === "" ? null : Number(e.target.value) })}
        className="w-20 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
      />
    </div>
  );
}

export function ScreenerFilters({ filters, onFiltersChange, sectors, companyTypes, sortField, sortDirection, onSortChange }: Props) {
  function patch(partial: Partial<ScreenerFilterState>) {
    onFiltersChange({ ...filters, ...partial });
  }

  return (
    <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <RangeInput label="Overall" value={filters.overallScore} onChange={(r) => patch({ overallScore: r })} />
        <RangeInput label="Step 1" value={filters.step1Score} onChange={(r) => patch({ step1Score: r })} />
        <RangeInput label="Step 2" value={filters.step2Score} onChange={(r) => patch({ step2Score: r })} />
        <RangeInput label="Step 4" value={filters.step4Score} onChange={(r) => patch({ step4Score: r })} />
        <RangeInput label="Step 5" value={filters.step5Score} onChange={(r) => patch({ step5Score: r })} />
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <RangeInput label="Mkt Cap" value={filters.marketCap} onChange={(r) => patch({ marketCap: r })} />
        <RangeInput label="P/E" value={filters.peRatio} onChange={(r) => patch({ peRatio: r })} />
        <RangeInput label="Beta" value={filters.beta} onChange={(r) => patch({ beta: r })} />
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-3">
        <MultiSelectDropdown label="Sector" options={sectors} selected={filters.sectors} onChange={(s) => patch({ sectors: s })} />
        <MultiSelectDropdown
          label="Company type"
          options={companyTypes}
          selected={filters.companyTypes}
          onChange={(s) => patch({ companyTypes: s })}
        />

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-zinc-500">Sort</span>
          <select
            value={sortField}
            onChange={(e) => onSortChange(e.target.value as SortField, sortDirection)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-zinc-500 focus:outline-none"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => onSortChange(sortField, sortDirection === "asc" ? "desc" : "asc")}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
            title={sortDirection === "asc" ? "Ascending" : "Descending"}
          >
            {sortDirection === "asc" ? "↑ Asc" : "↓ Desc"}
          </button>
        </div>
      </div>
    </div>
  );
}
