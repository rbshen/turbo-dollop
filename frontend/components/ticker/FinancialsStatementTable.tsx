"use client";

import { CaretDown, Info } from "@phosphor-icons/react";
import { Fragment, useState } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DataQualityFlag, FinancialsPeriodOut } from "@/lib/api/types";
import { columnMarkers, type StatementKind } from "@/lib/dataQuality";
import { fmtNumber, fmtTableNumber } from "@/lib/format";

interface Props {
  periodType: "annual" | "quarterly";
  data: FinancialsPeriodOut;
  // Read-time data-quality markers (backend data_quality_flags): an icon with a title tooltip on the affected column
  // headers. They only annotate -- no value in the table is hidden or replaced.
  statement?: StatementKind;
  dataQuality?: DataQualityFlag[];
}

// Confirmed by investigation: FMP's data for these two specific fields is
// genuinely incomplete for a meaningful slice of tickers (e.g. MSFT reads
// $0 for every cached period despite the company's own filings showing real,
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
export function FinancialsStatementTable({ periodType, data, statement, dataQuality }: Props) {
  const columnCount = data.periods.length + 1;
  // Every group starts expanded (matches the pre-collapse behavior) --
  // groups without a label (Income Statement's flat rows) never appear in
  // this set since there's no header row to click.
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
    <Table containerClassName="max-h-[70vh] overflow-y-auto" className="border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className="sticky left-0 top-0 z-30 whitespace-nowrap border-b border-border-subtle bg-page pr-8">
            Metric
          </TableHead>
          {data.periods.map((period, i) => (
            <TableHead
              key={i}
              className="sticky top-0 z-20 whitespace-nowrap border-b border-border-subtle bg-page text-right"
            >
              {statement &&
                columnMarkers(dataQuality, statement, periodType, period).map((marker, mi) => (
                  <span
                    key={mi}
                    role="img"
                    aria-label={marker.message}
                    className="mr-1.5 inline-flex align-middle text-warn"
                    title={marker.evidence ? `${marker.message} (${marker.evidence})` : marker.message}
                  >
                    <Info size={13} weight="bold" aria-hidden="true" />
                  </span>
                ))}
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
                <TableRow dense className="cursor-pointer" onClick={() => toggle(gi)}>
                  <TableCell className="sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-page pr-8 pt-4 pb-1 text-sm font-medium text-text-primary">
                    <span className="inline-flex items-center gap-1.5">
                      <CaretDown size={12} className={`text-text-tertiary transition-transform duration-200 ${isOpen ? "" : "-rotate-90"}`} />
                      {group.label}
                    </span>
                  </TableCell>
                  <TableCell colSpan={columnCount - 1} className="border-b border-border-subtle pt-4 pb-1" />
                </TableRow>
              )}
              {(!group.label || isOpen) &&
                group.items.map((item) => (
                  <TableRow key={item.label} dense>
                    <TableCell
                      className={`sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-page pr-8 ${
                        group.label ? "pl-4" : "pl-0"
                      } ${item.emphasis ? "font-medium text-text-primary" : "text-text-secondary"}`}
                    >
                      {item.label}
                      {INCOMPLETE_COVERAGE_LABELS.has(item.label) && (
                        <span className="ml-1.5 inline-flex align-middle text-text-tertiary" title={INCOMPLETE_COVERAGE_NOTE}>
                          <Info size={13} weight="bold" />
                        </span>
                      )}
                    </TableCell>
                    {item.values.map((value, i) => (
                      <TableCell
                        key={i}
                        className={`border-b border-border-subtle text-right font-mono tabular-nums ${
                          item.emphasis ? "font-medium text-text-primary" : "text-text-secondary"
                        }`}
                      >
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
