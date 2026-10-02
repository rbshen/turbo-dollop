"use client";

import { ArrowDown, ArrowUp } from "@phosphor-icons/react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/Select";
import type { SortDirection, SortField } from "@/lib/screenerFilters";

// Option VALUES are the stored/sent SortField keys and never change; the labels
// are display-only sentence case.
export const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "overall_score", label: "Overall score" },
  { value: "step1_score", label: "Financials score" },
  { value: "step2_score", label: "Growth rate score" },
  { value: "step4_score", label: "Profitability score" },
  { value: "step5_score", label: "Debt score" },
  { value: "last_price", label: "Quote" },
  { value: "market_cap", label: "Market cap" },
  { value: "pe_ratio", label: "P/E" },
  { value: "beta", label: "Beta" },
  { value: "growth_rate", label: "Growth rate" },
  { value: "warren_signal_recency", label: "Warren signal recency" },
  { value: "weinstein_stage_since", label: "Weinstein: stage since" },
];

interface Props<F extends string> {
  sortField: F;
  sortDirection: SortDirection;
  onChange: (field: F, direction: SortDirection) => void;
  // The field choices. The Stocks page passes none and gets SORT_OPTIONS; the ETFs page passes its own.
  options?: readonly { value: F; label: string }[];
}

// The results header's Sort row: a labelled native Select for the field (size
// "wide": "medium" clips the longest label, "Warren signal recency") and one
// outline toggle for the direction. The Button's default size is 36px, the same
// height as the Select. Wraps below lg instead of overflowing.
export function SortControls<F extends string = SortField>({
  sortField,
  sortDirection,
  onChange,
  options = SORT_OPTIONS as unknown as readonly { value: F; label: string }[],
}: Props<F>) {
  const fieldId = useId();
  const descending = sortDirection === "desc";
  const DirectionIcon = descending ? ArrowDown : ArrowUp;
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <label htmlFor={fieldId} className="text-xs text-text-secondary">
        Sort by
      </label>
      <Select id={fieldId} size="wide" value={sortField} onChange={(e) => onChange(e.target.value as F, sortDirection)}>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </Select>
      <Button
        variant="outline"
        onClick={() => onChange(sortField, descending ? "asc" : "desc")}
        aria-label={`Sort direction: ${descending ? "descending" : "ascending"}. Switch to ${descending ? "ascending" : "descending"}.`}
      >
        <DirectionIcon size={14} aria-hidden="true" />
        {descending ? "Desc" : "Asc"}
      </Button>
    </div>
  );
}
