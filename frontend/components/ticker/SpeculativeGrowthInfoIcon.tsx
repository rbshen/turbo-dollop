"use client";

import { useState } from "react";
import { Info } from "@phosphor-icons/react";

// Fixed copy per design sign-off -- not derived from live data (unlike
// SpeculativeGrowthPill's own `buildTooltip`, which is a numeric breakdown
// of this specific ticker). This is the same static explainer regardless
// of which qualifying ticker it's shown next to.
export const SPECULATIVE_GROWTH_INFO_COPY =
  "A fast-growing, not-yet-profitable company. Standard scoring criteria (like moat and debt) don't fully apply here — growth and cash runway matter more than current profits.";

// Desktop: hover/focus shows the tooltip (`hovered`). Touch devices don't
// fire hover at all, so a tap must also work -- toggled independently via
// `tapped` so a click while already hovering (desktop) doesn't fight the
// hover state closed. `visible` is the OR of both; the panel is only
// mounted (not just visually hidden) while `visible` is false, but since
// it's absolutely positioned this never affects layout either way.
export function SpeculativeGrowthInfoIcon() {
  const [hovered, setHovered] = useState(false);
  const [tapped, setTapped] = useState(false);
  const visible = hovered || tapped;

  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        aria-label="About Speculative Growth"
        aria-describedby="speculative-growth-info-tooltip"
        aria-expanded={visible}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={() => setTapped((v) => !v)}
        className="inline-flex items-center justify-center rounded-full text-text-tertiary transition-colors hover:text-text-secondary focus:outline-none focus-visible:text-text-secondary"
      >
        <Info size={14} weight="bold" />
      </button>
      {visible && (
        <div
          id="speculative-growth-info-tooltip"
          role="tooltip"
          className="absolute left-1/2 top-full z-20 mt-1.5 w-64 -translate-x-1/2 rounded-md border border-border-input bg-surface p-2.5 text-xs font-normal leading-snug text-text-secondary shadow-lg"
        >
          {SPECULATIVE_GROWTH_INFO_COPY}
        </div>
      )}
    </span>
  );
}
