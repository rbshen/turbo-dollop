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
export function SortHeader({ label, active, direction, priority, onClick, align = "left", className }: SortHeaderProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex w-full items-center gap-1 text-xs font-medium text-text-tertiary transition-colors hover:text-text-primary",
        align === "right" ? "justify-end" : "justify-start",
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
