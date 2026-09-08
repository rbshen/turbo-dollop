"use client";

import { useState } from "react";
import { Warning } from "@phosphor-icons/react";

// Fixed copy per design sign-off -- distinct from SPECULATIVE_GROWTH_INFO_COPY
// (SpeculativeGrowthInfoIcon.tsx), which explains the classification itself;
// this explains why THIS specific ticker's qualification may be less
// reliable than usual. See scoring/speculative_growth.py::
// is_potential_fake_growth's own docstring for the exact mechanism (revenue
// >30% below its trailing-5yr peak AND trailing YoY growth under half of
// the forward CAGR that cleared the growth gate) -- MRNA is the confirmed
// real case that motivated this check.
export const SPECULATIVE_GROWTH_FAKE_GROWTH_COPY =
  "Recent growth may be inflated by a depressed prior-year base rather than genuine momentum — check trailing growth and revenue trend before relying on this qualification.";

// Same hover(desktop)/tap(touch)-toggle interaction as SpeculativeGrowthInfoIcon,
// kept as a separate component (not a shared abstraction) since the two
// differ in icon, color, aria-label, tooltip id, and copy -- see that
// file's own comment for the interaction design rationale.
export function SpeculativeGrowthFakeGrowthWarning() {
  const [hovered, setHovered] = useState(false);
  const [tapped, setTapped] = useState(false);
  const visible = hovered || tapped;

  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        aria-label="Potential fake growth warning"
        aria-describedby="speculative-growth-fake-growth-tooltip"
        aria-expanded={visible}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={() => setTapped((v) => !v)}
        className="inline-flex items-center justify-center rounded-full text-warn transition-colors hover:text-warn/80 focus:outline-none focus-visible:text-warn/80"
      >
        <Warning size={14} weight="bold" />
      </button>
      {visible && (
        <div
          id="speculative-growth-fake-growth-tooltip"
          role="tooltip"
          className="absolute left-1/2 top-full z-20 mt-1.5 w-64 -translate-x-1/2 rounded-md border border-warn/40 bg-surface p-2.5 text-xs font-normal leading-snug text-text-secondary shadow-lg"
        >
          {SPECULATIVE_GROWTH_FAKE_GROWTH_COPY}
        </div>
      )}
    </span>
  );
}
