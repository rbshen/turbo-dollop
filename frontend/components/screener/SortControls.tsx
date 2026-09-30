"use client";

import { ArrowDown, ArrowUp } from "@phosphor-icons/react";

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

const SORT_FIELD_ID = "screener-sort-field";

interface Props {
  sortField: SortField;
  sortDirection: SortDirection;
  onChange: (field: SortField, direction: SortDirection) => void;
}

// The results header's Sort row: a labelled native Select for the field (size
// "wide": "medium" clips the longest label, "Warren signal recency") and one
// outline toggle for the direction. The Button's default size is 36px, the same
// height as the Select. Wraps below lg instead of overflowing.
export function SortControls({ sortField, sortDirection, onChange }: Props) {
  const descending = sortDirection === "desc";
  const DirectionIcon = descending ? ArrowDown : ArrowUp;
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <label htmlFor={SORT_FIELD_ID} className="text-xs text-text-secondary">
        Sort by
      </label>
      <Select id={SORT_FIELD_ID} size="wide" value={sortField} onChange={(e) => onChange(e.target.value as SortField, sortDirection)}>
        {SORT_OPTIONS.map((opt) => (
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
