"use client"

import * as React from "react"
import { CaretDown, CaretUp } from "@phosphor-icons/react"

import { cn } from "@/lib/utils"

export type SortDirection = "asc" | "desc"

interface SortHeaderProps {
  label: React.ReactNode
  /** Whether this column is the (or a) currently active sort column. */
  active: boolean
  /** Required when `active`; ignored otherwise. */
  direction?: SortDirection
  /** 1-based priority shown beside the arrow in a multi-column sort; omit for a single active column. */
  priority?: number
  onClick: () => void
  /** Matches the column's own text alignment -- flips the button to fill and right-align within the cell. */
  align?: "left" | "right"
  className?: string
}

// One sort look app-wide: a ghost button living inside a TableHead. Inactive
// columns show no arrow at all; the active column's label and arrow both
// turn text-text-primary, with the priority numeral (mono, multi-sort only)
// trailing the arrow. The parent TableHead carries aria-sort -- this button
// is purely the visual/interactive layer.
//
// `align="left"` (the default, used for left- AND center-aligned columns
// alike) stays a plain inline-flex box -- an inline-level element already
// takes its position from the <th>'s own text-align, so a centered column
// just works without this component needing to know it's centered.
// `align="right"` additionally spans the full cell (w-full justify-end):
// a numeric column is usually much wider than its label, so this gives a
// right-anchored, full-width click/hover target instead of a tight box
// hugging just the label text.
export function SortHeader({ label, active, direction, priority, onClick, align = "left", className }: SortHeaderProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium text-text-tertiary transition-colors hover:text-text-primary",
        align === "right" && "w-full justify-end",
        active && "text-text-primary",
        className
      )}
    >
      <span>{label}</span>
      {active && (direction === "asc" ? <CaretUp size={13} /> : <CaretDown size={13} />)}
      {active && priority != null && <span className="font-mono text-[13px]">{priority}</span>}
    </button>
  )
}
