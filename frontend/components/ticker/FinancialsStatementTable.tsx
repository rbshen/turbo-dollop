import { Info } from "@phosphor-icons/react";
import { Fragment } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { FinancialsPeriodOut } from "@/lib/api/types";
import { fmtNumber, fmtTableNumber } from "@/lib/format";

interface Props {
  data: FinancialsPeriodOut;
}

// Confirmed by investigation: FMP's data for these two specific fields is
// genuinely incomplete for a meaningful slice of tickers (e.g. MSFT reads
// $0 for every cached period despite SEC EDGAR's own filings showing real,
// nonzero figures) -- and FMP sends a literal 0 rather than null for the
// missing case, so the gap isn't otherwise visible to a reader the way an
// em-dash ("—", used for actual nulls) would be. Applies regardless of
// whether the currently-displayed period happens to have a real number.
const INCOMPLETE_COVERAGE_LABELS = new Set(["Income Taxes Paid", "Interest Paid"]);
const INCOMPLETE_COVERAGE_NOTE =
  "Data source coverage for this line is incomplete — a $0 here may mean no data was reported, not that the actual amount was zero.";

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
                  {INCOMPLETE_COVERAGE_LABELS.has(item.label) && (
                    <span className="ml-1.5 inline-flex align-middle text-zinc-500" title={INCOMPLETE_COVERAGE_NOTE}>
                      <Info size={13} weight="bold" />
                    </span>
                  )}
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
