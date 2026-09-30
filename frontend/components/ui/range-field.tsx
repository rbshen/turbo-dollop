"use client";

// RangeField -- one labelled Min/Max pair for a numeric range filter (the
// Screener sidebar's Overall, Quote, Mkt cap, P/E ...). Built from the compact
// FormField (label row with a right-aligned unit) and two NumberFields.
//
// It is role="group" named by its label; the boxes are "Minimum" and "Maximum"
// with the placeholders "Min" and "Max". The value and onChange are numeric
// `{ min, max }` -- typed text lives in a per-side draft (useDraftNumber), so
// the filter state stays numeric. Commit rule (full text in the hook and in
// docs/design-system.md): valid text commits at once, an incomplete prefix
// ("-", ".") holds the previous value and errors on blur, any other invalid
// text makes that side inactive (null) with an error, nothing is ever clamped,
// swapped or corrected.
//
// One error line sits under the pair, never one per box: a text error wins,
// else, if min is higher than max, the reversed-range message (applied
// literally -- nothing matches -- with only the Max box marked invalid).
//
// Parents must pass the object from onChange back unchanged: a different
// object is read as an external change (Reset, Load) and rewrites the boxes.
import { useId, useRef } from "react";
import { FormField } from "@/components/ui/form-field";
import { NumberField } from "@/components/ui/number-field";
import { useDraftNumber } from "@/lib/hooks/useDraftNumber";
import type { FieldSize } from "@/lib/formControl";
import type { NumberSuffixes } from "@/lib/numberInput";

export interface RangeValue {
  min: number | null;
  max: number | null;
}

export const REVERSED_RANGE_MESSAGE = "Min is higher than max, so no ticker can match.";

export interface RangeFieldProps {
  label: string;
  value: RangeValue;
  onChange: (value: RangeValue) => void;
  /** Shown right-aligned in the label row ("USD", "x", "%"); none for a score. */
  unit?: string;
  /** Width token of each box. Default "short" (96px). */
  size?: FieldSize;
  /** Suffix parsing for a market cap: `{ M: 1e6, B: 1e9, T: 1e12 }`. */
  suffixes?: NumberSuffixes;
  /** A lower bound for both boxes (market cap: 0). No other bound is ever applied. */
  min?: number;
  variant?: "boxed" | "underline";
  /** One optional single-line hint under the pair (market cap only). */
  hint?: string;
  id?: string;
  className?: string;
}

export function RangeField({
  label,
  value,
  onChange,
  unit,
  size = "short",
  suffixes,
  min,
  variant = "boxed",
  hint,
  id,
  className,
}: RangeFieldProps) {
  const autoId = useId();
  const baseId = id ?? `range-${autoId}`;
  const minId = `${baseId}-min`;
  const maxId = `${baseId}-max`;
  const labelId = `${baseId}-label`;
  const lastEmitted = useRef<unknown>(value);

  const minDraft = useDraftNumber({ value: value.min, owner: value, lastEmitted, suffixes, min });
  const maxDraft = useDraftNumber({ value: value.max, owner: value, lastEmitted, suffixes, min });

  function commit(side: "min" | "max", outcome: { emit: false } | { emit: true; value: number | null }) {
    if (!outcome.emit) return;
    const next = { ...value, [side]: outcome.value };
    lastEmitted.current = next;
    onChange(next);
  }

  const reversed = value.min != null && value.max != null && value.min > value.max;
  const textError = minDraft.error ?? maxDraft.error;
  const pairError = textError ?? (reversed ? REVERSED_RANGE_MESSAGE : null);
  const applied = value.min != null || value.max != null;

  return (
    <FormField
      label={label}
      htmlFor={minId}
      labelId={labelId}
      density="compact"
      unit={unit}
      hint={hint}
      error={pairError}
      applied={applied}
      role="group"
      aria-labelledby={labelId}
      className={className}
    >
      <div className="flex items-center gap-1.5">
        <NumberField
          id={minId}
          aria-label="Minimum"
          placeholder="Min"
          value={minDraft.draft}
          onChange={(text) => commit("min", minDraft.change(text))}
          onFocus={minDraft.focus}
          onBlur={() => commit("min", minDraft.blur())}
          invalid={Boolean(minDraft.error)}
          size={size}
          variant={variant}
          suffixes={suffixes}
          min={min}
          optional
          keyboardStep={false}
          hideError
        />
        <span aria-hidden className="shrink-0 text-xs text-text-tertiary">
          –
        </span>
        <NumberField
          id={maxId}
          aria-label="Maximum"
          placeholder="Max"
          value={maxDraft.draft}
          onChange={(text) => commit("max", maxDraft.change(text))}
          onFocus={maxDraft.focus}
          onBlur={() => commit("max", maxDraft.blur())}
          invalid={Boolean(maxDraft.error) || (reversed && !textError)}
          size={size}
          variant={variant}
          suffixes={suffixes}
          min={min}
          optional
          keyboardStep={false}
          hideError
        />
      </div>
    </FormField>
  );
}
