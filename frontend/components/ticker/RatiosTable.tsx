"use client";

import { CaretDown } from "@phosphor-icons/react";
import { Fragment, useState } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { RatiosOut } from "@/lib/api/types";
import { fmtDays, fmtNumber, fmtPlainPct, fmtRatio, fmtTableNumber } from "@/lib/format";

interface Props {
  data: RatiosOut;
}

function formatValue(value: number | null, unit: string): string {
  if (value == null) return "—";
  switch (unit) {
    case "per_share":
      return fmtNumber(value);
    case "ratio":
      return fmtRatio(value);
    case "percent":
      return fmtPlainPct(value);
    case "days":
      return fmtDays(value);
    default:
      // "money" / "shares"
      return fmtTableNumber(value);
  }
}

// Same sticky-label-column/group-header/right-aligned-numeric-column
// structure as FinancialsStatementTable -- Ratios has no annual/quarterly
// toggle (FMP 402s on quarterly key-metrics/ratios under our plan), so
// there's no period-count/column-count branching to carry over.
export function RatiosTable({ data }: Props) {
  const columnCount = data.periods.length + 1;
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  function toggle(gi: number) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(gi)) next.delete(gi);
      else next.add(gi);
      return next;
    });
  }

  return (
    <Table
      containerClassName="max-h-[70vh] overflow-y-auto rounded-lg border border-border-card bg-surface"
      className="border-separate border-spacing-0 text-sm"
    >
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="sticky left-0 top-0 z-30 whitespace-nowrap border-b border-border-card bg-surface-2 py-2 pr-8 text-xs font-medium uppercase tracking-widest text-text-secondary">
            Metric
          </TableHead>
          {data.periods.map((period, i) => (
            <TableHead
              key={i}
              className="sticky top-0 z-20 whitespace-nowrap border-b border-border-card bg-surface-2 py-2 pr-4 text-right text-xs font-medium uppercase tracking-widest text-text-secondary"
            >
              {period}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.groups.map((group, gi) => {
          const isOpen = !collapsed.has(gi);
          return (
            <Fragment key={gi}>
              {group.label && (
                <TableRow className="cursor-pointer hover:bg-transparent" onClick={() => toggle(gi)}>
                  <TableCell className="sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-surface pt-4 pb-1 text-xs font-semibold uppercase tracking-widest text-text-secondary">
                    <span className="inline-flex items-center gap-1.5">
                      <CaretDown size={12} className={`transition-transform duration-200 ${isOpen ? "" : "-rotate-90"}`} />
                      {group.label}
                    </span>
                  </TableCell>
                  <TableCell colSpan={columnCount - 1} className="border-b border-border-subtle pt-4 pb-1" />
                </TableRow>
              )}
              {(!group.label || isOpen) &&
                group.items.map((item) => (
                  <TableRow key={item.label} className="hover:bg-transparent">
                    <TableCell
                      className={`sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-surface py-2 pr-8 text-text-secondary ${
                        group.label ? "pl-4" : ""
                      }`}
                    >
                      {item.label}
                    </TableCell>
                    {item.values.map((value, i) => (
                      <TableCell key={i} className="border-b border-border-subtle py-2 pr-4 text-right font-mono tabular-nums text-text-secondary">
                        {formatValue(value, item.unit)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
