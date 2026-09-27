"use client";

import { useState } from "react";
import { Minus, Plus } from "@phosphor-icons/react";

// Bounded numeric stepper (up/down spin-box): a typable input flanked by
// -/+ buttons. Typing is still allowed (a click-only control would need up
// to (max-min)/step clicks to move breach_recency_bars from 1 to 52), but
// the value is always clamped to [min, max] and snapped to the nearest
// `step` increment on blur/Enter -- so the parent never sees an invalid or
// off-grid number, regardless of how the value changed.
export function NumberStepper({
  id,
  value,
  onChange,
  min,
  max,
  step,
  disabled = false,
}: {
  id: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
}) {
  // Initial value only -- every later change to `value` (a +/- click or a
  // blur-commit) round-trips through commit() below, which keeps `draft` in
  // sync itself. The parent form remounts this component wholesale on save
  // (keyed on updated_at, the same convention every settings form on this
  // page already uses), so no external re-sync is needed here.
  const [draft, setDraft] = useState(String(value));

  function commit(next: number) {
    const clamped = Math.min(max, Math.max(min, next));
    // Snap to the nearest step increment relative to min, avoiding float
    // drift (e.g. cluster_pct's 0.1 step) via a rounding-count roundtrip.
    const steps = Math.round((clamped - min) / step);
    const snapped = Math.round((min + steps * step) * 1e6) / 1e6;
    onChange(snapped);
    setDraft(String(snapped));
  }

  function handleBlur() {
    const parsed = parseFloat(draft);
    if (Number.isNaN(parsed)) {
      setDraft(String(value));
      return;
    }
    commit(parsed);
  }

  // Same class vocabulary as the form's own Save button (border-zinc-700/
  // bg-zinc-800/hover:bg-zinc-700) rather than a separate, subtly-different
  // zinc-900/zinc-800 combination -- keeps every button on this page
  // visually consistent with the one the styling report called out as
  // "styled correctly".
  const buttonCls =
    "flex h-[30px] w-7 shrink-0 items-center justify-center rounded-md border border-zinc-700 bg-zinc-800 text-zinc-200 transition-colors hover:border-zinc-500 hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-zinc-700 disabled:hover:bg-zinc-800";

  return (
    <div className="mt-1 flex items-center gap-1">
      <button
        type="button"
        aria-label="Decrease"
        className={buttonCls}
        disabled={disabled || value <= min}
        onClick={() => commit(value - step)}
      >
        <Minus size={12} weight="bold" />
      </button>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        disabled={disabled}
        className="w-full min-w-0 appearance-none rounded border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-center font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none disabled:opacity-40"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          }
        }}
      />
      <button
        type="button"
        aria-label="Increase"
        className={buttonCls}
        disabled={disabled || value >= max}
        onClick={() => commit(value + step)}
      >
        <Plus size={12} weight="bold" />
      </button>
    </div>
  );
}
