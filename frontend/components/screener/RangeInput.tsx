"use client";

import { Field, Input } from "@/components/ui/input";
import type { RangeFilter } from "@/lib/screenerFilters";

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
//
// One Field wraps both Min/Max inputs -- the label describes the pair, not
// either input alone, so htmlFor points at Min (the first, tab-reached
// input) rather than duplicating the label per side.
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
  const id = `range-${label.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <Field label={label} htmlFor={`${id}-min`} applied={active}>
      <div className="flex items-center gap-1.5">
        <Input
          id={`${id}-min`}
          type="number"
          placeholder="Min"
          value={value.min ?? ""}
          onChange={(e) => onChange({ ...value, min: e.target.value === "" ? null : Number(e.target.value) })}
          className="w-0 min-w-0 flex-1"
        />
        <span className="shrink-0 text-text-tertiary">–</span>
        <Input
          id={`${id}-max`}
          type="number"
          placeholder="Max"
          value={value.max ?? ""}
          onChange={(e) => onChange({ ...value, max: e.target.value === "" ? null : Number(e.target.value) })}
          className="w-0 min-w-0 flex-1"
        />
      </div>
    </Field>
  );
}
