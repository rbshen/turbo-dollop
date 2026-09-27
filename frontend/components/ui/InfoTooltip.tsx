"use client";

import { useId, useState } from "react";
import { Info } from "@phosphor-icons/react";

// Generalized from components/ticker/SpeculativeGrowthInfoIcon.tsx's
// hover/tap mechanism (that one has fixed, hardcoded copy tied to a single
// feature; this one takes label/text so it can be reused anywhere a plain
// field-level help tooltip is needed). Styled with this app's raw zinc-*
// palette to match Settings-page components, rather than the design-token
// classes the ticker-page version uses.
//
// Desktop: hover/focus shows the tooltip. Touch devices don't fire hover at
// all, so a tap must also work -- toggled independently via `tapped` so a
// click while already hovering (desktop) doesn't fight the hover state
// closed. `visible` is the OR of both.
export function InfoTooltip({ label, text }: { label: string; text: string }) {
  const [hovered, setHovered] = useState(false);
  const [tapped, setTapped] = useState(false);
  const visible = hovered || tapped;
  const tooltipId = useId();

  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        aria-label={label}
        aria-describedby={tooltipId}
        aria-expanded={visible}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={() => setTapped((v) => !v)}
        className="inline-flex items-center justify-center rounded-full text-zinc-500 transition-colors hover:text-zinc-300 focus:outline-none focus-visible:text-zinc-300"
      >
        <Info size={13} weight="bold" />
      </button>
      {visible && (
        <div
          id={tooltipId}
          role="tooltip"
          className="absolute left-1/2 top-full z-20 mt-1.5 w-64 -translate-x-1/2 rounded-md border border-zinc-800 bg-zinc-950 p-2.5 text-xs font-normal leading-snug text-zinc-300 shadow-lg"
        >
          {text}
        </div>
      )}
    </span>
  );
}
