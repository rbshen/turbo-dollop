"use client";

import { FILTER_ACTIVE_LABEL_CLASS, type RangeFilter } from "@/lib/screenerFilters";
import { cn } from "@/lib/utils";

// Label stacked above a Min/Max row, each input sized via flex-1/min-w-0
// rather than a fixed width -- a fixed w-24 label + 2x w-20 inputs (the old
// single-row layout, sized for the full-width top bar this used to live in)
// overflows a ~224px sidebar column's actual content width. Stacking keeps
// this correct at any sidebar width instead of depending on a specific one.
//
// Shared between FundamentalFilters.tsx and TechnicalFilters.tsx (the
// latter for Beta, moved there 2026-09 -- a price-covariance statistic,
// not an accounting metric) rather than duplicated or imported cross-
// section, since both sections use the identical Min/Max range shape.
export function RangeInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: RangeFilter;
  onChange: (range: RangeFilter) => void;
}) {
  const active = value.min != null || value.max != null;

  return (
    <div className="space-y-1">
      <span className={cn("text-xs", active ? FILTER_ACTIVE_LABEL_CLASS : "text-text-tertiary")}>{label}</span>
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
