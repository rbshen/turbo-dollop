import { Fragment } from "react";

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

  return (
    <Table className="border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="sticky left-0 z-10 whitespace-nowrap border-b border-zinc-800 bg-zinc-950 py-2 pr-8 text-xs font-medium uppercase tracking-widest text-zinc-500">
            Metric
          </TableHead>
          {data.periods.map((period, i) => (
            <TableHead
              key={i}
              className="whitespace-nowrap border-b border-zinc-800 py-2 pr-4 text-right text-xs font-medium uppercase tracking-widest text-zinc-500"
            >
              {period}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.groups.map((group, gi) => (
          <Fragment key={gi}>
            {group.label && (
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={columnCount}
                  className="border-b border-zinc-900 pt-4 pb-1 text-xs font-semibold uppercase tracking-widest text-zinc-500"
                >
                  {group.label}
                </TableCell>
              </TableRow>
            )}
            {group.items.map((item) => (
              <TableRow key={item.label} className="hover:bg-transparent">
                <TableCell className="sticky left-0 z-10 whitespace-nowrap border-b border-zinc-900 bg-zinc-950 py-2 pr-8 text-zinc-400">
                  {item.label}
                </TableCell>
                {item.values.map((value, i) => (
                  <TableCell
                    key={i}
                    className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-300"
                  >
                    {formatValue(value, item.unit)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </Fragment>
        ))}
      </TableBody>
    </Table>
  );
}
