"use client";

import { CaretDown, Info } from "@phosphor-icons/react";
import { Fragment, useState } from "react";

import { SecCellCheckButton, type SecCellCheckField } from "@/components/ticker/SecCellCheckButton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { FinancialsPeriodOut } from "@/lib/api/types";
import { fmtNumber, fmtTableNumber } from "@/lib/format";

interface Props {
  ticker: string;
  // Phase 3a's SEC cell-check trigger only applies to the annual table --
  // TTM's cash-flow figure is a derived sum of 4 quarters (no single SEC
  // fact to check it against), and the quarterly table's own period labels
  // ("Q2 2026") aren't real dates the backend can look up. See
  // SecCellCheckButton and the backend's get_cash_flow_cell_sec_check.
  periodType: "annual" | "quarterly";
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

// Same two rows as INCOMPLETE_COVERAGE_LABELS, mapped to the backend's own
// field key -- kept as a separate map (not folded into a set-of-tuples)
// since INCOMPLETE_COVERAGE_LABELS is also used standalone above for the
// info-icon tooltip, which applies regardless of periodType.
const CELL_CHECK_FIELDS: Record<string, SecCellCheckField> = {
  "Income Taxes Paid": "incomeTaxesPaid",
  "Interest Paid": "interestPaid",
};

// Annual periods are real ISO fiscal-year-end dates ("2025-06-30"); the TTM
// column ("TTM (2026-06-30)") and padding rows ("—") are not -- only a
// plain date can be sent to the backend as period_end.
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

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
export function FinancialsStatementTable({ ticker, periodType, data }: Props) {
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
                      className={`sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-surface py-2 pr-8 ${
                        group.label ? "pl-4" : ""
                      } ${item.emphasis ? "font-medium text-text-primary" : "text-text-secondary"}`}
                    >
                      {item.label}
                      {INCOMPLETE_COVERAGE_LABELS.has(item.label) && (
                        <span className="ml-1.5 inline-flex align-middle text-text-tertiary" title={INCOMPLETE_COVERAGE_NOTE}>
                          <Info size={13} weight="bold" />
                        </span>
                      )}
                    </TableCell>
                    {item.values.map((value, i) => {
                      const cellCheckField = CELL_CHECK_FIELDS[item.label];
                      const periodEnd = data.periods[i];
                      // Only offer the trigger where it's meaningful: the
                      // annual table, a genuine zero/blank cell, and a
                      // column whose period is a real date the backend can
                      // look up (excludes the TTM column and any padding).
                      const showCellCheck =
                        cellCheckField != null && periodType === "annual" && !value && ISO_DATE_RE.test(periodEnd);
                      return (
                        <TableCell
                          key={i}
                          className={`border-b border-border-subtle py-2 pr-4 text-right font-mono tabular-nums ${
                            item.emphasis ? "font-medium text-text-primary" : "text-text-secondary"
                          }`}
                        >
                          <span className="inline-flex items-center justify-end">
                            {formatValue(value, item.unit)}
                            {showCellCheck && (
                              <SecCellCheckButton ticker={ticker} field={cellCheckField} periodEnd={periodEnd} />
                            )}
                          </span>
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
