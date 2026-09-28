"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

function Table({
  className,
  containerClassName,
  ...props
}: React.ComponentProps<"table"> & { containerClassName?: string }) {
  return (
    <div
      data-slot="table-container"
      className={cn("relative w-full overflow-x-auto", containerClassName)}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-xs", className)}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead data-slot="table-header" className={className} {...props} />
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody data-slot="table-body" className={className} {...props} />
}

// h-11 (44px) is the DEFAULT body-row height; a sortable header row needs
// h-9 (36px) instead -- since this same component renders both, a header
// usage must pass an explicit h-9 override (twMerge resolves the conflict
// in the caller's favor either way). `dense` is the same h-9 height for a
// statement-style body row (many number rows) rather than a header --
// kept as its own boolean (twMerge-resolved against the h-11 default)
// rather than requiring every dense-table caller to pass a raw className
// override. No default hover -- a row that opens something on click opts
// in via `interactive`, which is the only thing that ever adds a hover
// fill in this design. The last row keeps its own border-b like every
// other row -- no `:last-child` exception -- since the table itself never
// draws a surrounding box that a last-row border would double up against.
function TableRow({
  className,
  interactive,
  dense,
  ...props
}: React.ComponentProps<"tr"> & { interactive?: boolean; dense?: boolean }) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "h-11 border-b border-border-subtle transition-colors",
        dense && "h-9",
        interactive && "cursor-pointer hover:bg-surface",
        className
      )}
      {...props}
    />
  )
}

// `sort` forwards straight to aria-sort on the <th> -- omit it entirely for
// a non-sortable column (React drops an undefined attribute), pass "none"
// for a sortable-but-inactive column, "ascending"/"descending" once active.
function TableHead({
  className,
  sort,
  ...props
}: React.ComponentProps<"th"> & { sort?: "ascending" | "descending" | "none" }) {
  return (
    <th
      data-slot="table-head"
      aria-sort={sort}
      className={cn(
        "h-9 pr-4 pl-0 text-left align-middle text-xs font-medium whitespace-nowrap text-text-tertiary",
        className
      )}
      {...props}
    />
  )
}

// No vertical padding of its own -- row height comes from TableRow's own
// h-11/h-9, not from cell padding, so a cell never needs to restate it.
function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn("pl-0 pr-4 align-middle whitespace-nowrap", className)}
      {...props}
    />
  )
}

export { Table, TableHeader, TableBody, TableHead, TableRow, TableCell }
