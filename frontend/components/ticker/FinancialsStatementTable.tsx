import { Fragment } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { FinancialsPeriodOut } from "@/lib/api/types";
import { fmtNumber, fmtTableNumber } from "@/lib/format";

interface Props {
  data: FinancialsPeriodOut;
}

function formatValue(value: number | null, unit: string): string {
  if (value == null) return "—";
  // "money" and "shares" both scale to millions with no suffix -- the
  // "figures in USD millions" note under the sub-tabs covers the scale
  // once instead of repeating a per-cell unit; "shares" rows spell out
  // "(millions)" in their own label since they aren't actually USD.
  return unit === "per_share" ? fmtNumber(value) : fmtTableNumber(value);
}

// Single table with a sticky label column, replacing the former two-tables-
// side-by-side layout -- that approach relied on independently laid-out
// label/value tables producing matching row heights, which broke every time
// a row's content (e.g. an empty group-header cell) rendered at a different
// height than its counterpart. One <tr> per line item can't drift out of
// alignment with itself.
export function FinancialsStatementTable({ data }: Props) {
  const columnCount = data.periods.length + 1;

  return (
    <Table className="border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="sticky left-0 z-10 whitespace-nowrap border-b border-zinc-800 bg-zinc-950 py-2 pr-8 text-xs font-medium uppercase tracking-widest text-zinc-500">
            Line item
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
                <TableCell
                  className={`sticky left-0 z-10 whitespace-nowrap border-b border-zinc-900 bg-zinc-950 py-2 pr-8 ${
                    item.emphasis ? "font-medium text-zinc-100" : "text-zinc-400"
                  }`}
                >
                  {item.label}
                </TableCell>
                {item.values.map((value, i) => (
                  <TableCell
                    key={i}
                    className={`border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums ${
                      item.emphasis ? "font-medium text-zinc-100" : "text-zinc-300"
                    }`}
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
