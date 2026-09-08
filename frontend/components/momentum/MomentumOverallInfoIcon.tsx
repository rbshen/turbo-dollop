"use client";

import { useState } from "react";
import { Info } from "@phosphor-icons/react";

// Same hover-or-tap tooltip mechanics as SpeculativeGrowthInfoIcon.tsx
// (touch devices don't fire hover, so a tap must also work) -- fixed copy
// for this one specific column, so it's its own small component rather
// than a shared one this codebase doesn't otherwise have yet.
const OVERALL_INFO_COPY = "Fathom's fundamentals score — shown for context only, not used in this ranking.";

export function MomentumOverallInfoIcon() {
  const [hovered, setHovered] = useState(false);
  const [tapped, setTapped] = useState(false);
  const visible = hovered || tapped;

  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        aria-label="About the Overall column"
        aria-describedby="momentum-overall-info-tooltip"
        aria-expanded={visible}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={() => setTapped((v) => !v)}
        className="inline-flex items-center justify-center rounded-full text-text-tertiary transition-colors hover:text-text-secondary focus:outline-none focus-visible:text-text-secondary"
      >
        <Info size={13} weight="bold" />
      </button>
      {visible && (
        <div
          id="momentum-overall-info-tooltip"
          role="tooltip"
          className="absolute right-0 top-full z-20 mt-1.5 w-56 rounded-md border border-border-input bg-surface p-2.5 text-xs font-normal leading-snug text-text-secondary shadow-lg"
        >
          {OVERALL_INFO_COPY}
        </div>
      )}
    </span>
  );
}
