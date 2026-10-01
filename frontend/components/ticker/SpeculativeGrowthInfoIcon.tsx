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
//
// The bubble sets `whitespace-normal` itself because it sits inside
// TickerHeader's nowrap pill group and would otherwise inherit
// `white-space: nowrap` and run on as one line. From md up it is centred
// under the icon (256px, never wider than the viewport minus 2rem); below md
// the icon wrapper is `static`, so the bubble anchors to the pill row
// (`relative` in TickerHeader) and starts at the row's left edge, which
// keeps it inside the screen wherever the pill wrapped to.
export function SpeculativeGrowthInfoIcon() {
  const [hovered, setHovered] = useState(false);
  const [tapped, setTapped] = useState(false);
  const visible = hovered || tapped;

  return (
    <span className="static inline-flex items-center md:relative">
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
        className="inline-flex items-center justify-center rounded-full text-text-tertiary transition-colors hover:text-text-secondary focus-visible:text-text-secondary"
      >
        <Info size={14} weight="bold" />
      </button>
      {visible && (
        <div
          id="speculative-growth-info-tooltip"
          role="tooltip"
          className="absolute top-full z-30 mt-1.5 w-64 max-w-[min(18rem,calc(100vw-2rem))] whitespace-normal rounded-md border border-border-input bg-surface p-2.5 text-left text-xs font-normal leading-snug text-text-secondary shadow-lg max-md:left-0 max-md:w-auto max-md:max-w-[min(20rem,100%)] md:left-1/2 md:-translate-x-1/2"
        >
          {SPECULATIVE_GROWTH_INFO_COPY}
        </div>
      )}
    </span>
  );
}
