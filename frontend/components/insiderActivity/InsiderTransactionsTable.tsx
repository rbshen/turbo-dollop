"use client";

import { ArrowSquareOut } from "@phosphor-icons/react";
import { useState } from "react";

import { SegmentedControl } from "@/components/shared/SegmentedControl";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { InsiderTransaction } from "@/lib/api/types";
import { fmtCompactNumber } from "@/lib/format";
import {
  INSIDER_VIEW_OPTIONS,
  type InsiderView,
  filterInsiderTransactions,
  fmtInsiderRole,
  fmtInsiderValue,
  fmtIsoDate,
} from "@/lib/insiderActivity";
import { cn } from "@/lib/utils";

interface Props {
  transactions: InsiderTransaction[];
  // Shared with the quarterly chart -- the tab owns it so one control drives both.
  view: InsiderView;
  onViewChange: (view: InsiderView) => void;
}

// A busy filer's fetched history runs to hundreds or thousands of lines, so
// only a page of them is in the DOM at a time.
const PAGE_SIZE = 100;

const HEAD = "whitespace-nowrap border-b border-border-card py-2 pr-6 text-xs font-medium uppercase tracking-widest text-text-secondary";

// Buy/sale rows get the app's green/red; every other type stays neutral --
// only an open-market trade is a directional signal.
function typeClass(kind: InsiderTransaction["kind"]): string {
  if (kind === "open_market_buy") return "text-positive";
  if (kind === "open_market_sale") return "text-negative";
  return "text-text-secondary";
}

// The tab defaults the view to open-market buys/sales; the toggle just
// filters the one fetched blob client-side (same convention as the
// Screener's own multi-selects) -- no refetch.
export function InsiderTransactionsTable({ transactions, view, onViewChange }: Props) {
  const [shown, setShown] = useState(PAGE_SIZE);
  const rows = filterInsiderTransactions(transactions, view === "all");
  const visible = rows.slice(0, shown);

  return (
    <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Transactions</h2>
        <SegmentedControl value={view} onChange={onViewChange} options={INSIDER_VIEW_OPTIONS} />
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-text-tertiary">
          No open-market buys or sales in the fetched filings
          {transactions.length > 0 ? " — switch to “All types” to see the other transactions." : "."}
        </p>
      ) : (
        <Table className="border-separate border-spacing-0 text-sm">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className={HEAD}>Date</TableHead>
              <TableHead className={HEAD}>Insider</TableHead>
              <TableHead className={HEAD}>Type</TableHead>
              <TableHead className={cn(HEAD, "text-right")}>Shares</TableHead>
              <TableHead className={cn(HEAD, "text-right")}>Value</TableHead>
              <TableHead className={cn(HEAD, "pr-0 text-right")}>
                <span className="sr-only">SEC filing</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((t, i) => {
              const role = fmtInsiderRole(t.insider_role);
              return (
                <TableRow key={`${t.transaction_date}-${t.insider_cik ?? t.insider_name}-${i}`} className="hover:bg-surface-2">
                  <TableCell className="whitespace-nowrap py-2 pr-6 text-text-secondary">{fmtIsoDate(t.transaction_date)}</TableCell>
                  <TableCell className="py-2 pr-6">
                    <span className="text-text-primary">{t.insider_name}</span>
                    <span className="block text-xs text-text-tertiary">
                      {[role, t.ownership].filter(Boolean).join(" · ")}
                    </span>
                  </TableCell>
                  <TableCell className={cn("whitespace-nowrap py-2 pr-6 font-medium", typeClass(t.kind))}>{t.type_label}</TableCell>
                  <TableCell className="py-2 pr-6 text-right font-mono tabular-nums">{fmtCompactNumber(t.shares)}</TableCell>
                  <TableCell
                    className={cn(
                      "whitespace-nowrap py-2 pr-6 text-right font-mono tabular-nums",
                      !t.has_cash_value && "font-sans text-xs text-text-tertiary"
                    )}
                  >
                    {fmtInsiderValue(t)}
                  </TableCell>
                  <TableCell className="py-2 text-right">
                    {t.sec_filing_url && (
                      <a
                        href={t.sec_filing_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="Open SEC filing"
                        title="Open SEC filing"
                        className="inline-flex text-text-tertiary transition-colors hover:text-text-primary"
                      >
                        <ArrowSquareOut size={16} />
                      </a>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      {rows.length > shown && (
        <div className="flex items-center justify-between gap-3 pt-1 text-xs text-text-tertiary">
          <span>
            Showing {visible.length} of {rows.length}
          </span>
          <button
            type="button"
            onClick={() => setShown((n) => n + PAGE_SIZE)}
            className="inline-flex h-8 items-center rounded-md px-3 font-medium text-text-secondary transition-colors hover:text-text-primary"
          >
            Show {Math.min(PAGE_SIZE, rows.length - shown)} more
          </button>
        </div>
      )}
    </div>
  );
}
