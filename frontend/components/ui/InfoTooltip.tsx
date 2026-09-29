"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { Info } from "@phosphor-icons/react";

import { computeTooltipGeometry, type TooltipGeometry } from "@/lib/tooltipPosition";

// Generalized from components/ticker/SpeculativeGrowthInfoIcon.tsx's
// hover/tap mechanism (that one has fixed, hardcoded copy tied to a single
// feature; this one takes label/text so it can be reused anywhere a plain
// field-level help tooltip is needed). Styled with the same design tokens
// as that ticker-page version.
//
// Desktop: hover/focus shows the tooltip. Touch devices don't fire hover at
// all, so a tap must also work -- toggled independently via `tapped` so a
// click while already hovering (desktop) doesn't fight the hover state
// closed. `visible` is the OR of both.
//
// Positioning is measured, not guessed: in a tightly-packed multi-column
// form a fixed-width panel centered under the icon can easily overlap the
// next field below it or bleed into a neighboring column. The panel always
// opens ABOVE the icon (avoids the field below, structurally, in every
// column) and is horizontally clamped to the viewport via
// lib/tooltipPosition.ts::computeTooltipGeometry -- correct regardless of
// which column the icon is in, without hardcoding column widths.
export function InfoTooltip({ label, text }: { label: string; text: string }) {
  const [hovered, setHovered] = useState(false);
  const [tapped, setTapped] = useState(false);
  const visible = hovered || tapped;
  const tooltipId = useId();

  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [geometry, setGeometry] = useState<TooltipGeometry | null>(null);

  // Runs only while visible (the panel, and so panelRef, only exists then) --
  // recomputed synchronously before paint, so a stale geometry value left
  // over from the panel's last open is never actually shown.
  useLayoutEffect(() => {
    if (!visible || !triggerRef.current || !panelRef.current) return;
    function reposition() {
      if (!triggerRef.current || !panelRef.current) return;
      const iconRect = triggerRef.current.getBoundingClientRect();
      const panelRect = panelRef.current.getBoundingClientRect();
      setGeometry(computeTooltipGeometry(iconRect, panelRect.width, panelRect.height, window.innerWidth));
    }
    reposition();
    window.addEventListener("resize", reposition);
    return () => window.removeEventListener("resize", reposition);
  }, [visible]);

  return (
    <span className="relative inline-flex items-center">
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-describedby={tooltipId}
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
          ref={panelRef}
          id={tooltipId}
          role="tooltip"
          style={{
            position: "fixed",
            left: geometry?.panelLeft ?? 0,
            top: geometry?.panelTop ?? 0,
            visibility: geometry ? "visible" : "hidden",
          }}
          className="z-20 w-56 rounded-md border border-border-input bg-surface p-2.5 text-xs font-normal leading-snug text-text-secondary shadow-lg"
        >
          {text}
          <span
            aria-hidden="true"
            style={{ left: geometry?.arrowLeft ?? 0 }}
            className="absolute top-full -mt-1 h-2 w-2 rotate-45 border-b border-r border-border-input bg-surface"
          />
        </div>
      )}
    </span>
  );
}
