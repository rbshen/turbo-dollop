"use client";

import { useMemo } from "react";

import { MoatPill } from "@/components/ticker/MoatPill";
import { PriceChange } from "@/components/ticker/PriceChange";
import { ValuationBadge } from "@/components/screener/ValuationBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { WatchlistOut, WatchlistRowOut, WatchlistSortField } from "@/lib/api/types";
import { fmtCompactMoney, fmtMoney, fmtNumber } from "@/lib/format";
import type { SortDirection } from "@/lib/screenerFilters";
import { flatChipClassFor } from "@/lib/tierColor";
import { removeTickerFromWatchlist } from "@/lib/hooks/useWatchlists";
import { sortWatchlistRows } from "@/lib/watchlistSort";

interface Props {
  watchlist: WatchlistOut;
  rows: WatchlistRowOut[] | undefined;
  error?: Error;
}

const HEAD_CLASS = "whitespace-nowrap text-xs font-semibold uppercase tracking-widest text-text-tertiary";

// The Analysis column collapses the 4 individual step chips into one
// overall_score/overall_verdict pill (see the column-order comment below) --
// that collapse means a step-level "Pass with caution" flag (currently only
// ever Step 5's) is otherwise invisible here even though it now drives the
// Analysis pill's own caution color (see lib/tierColor.ts). This names
// exactly which step(s) triggered it, surfaced as a small marker with a
// tooltip, without re-adding the removed per-step columns.
function cautionStepLabels(row: WatchlistRowOut): string[] {
  const labels: string[] = [];
  if (row.step1_verdict === "Pass with caution") labels.push("Financials");
  if (row.step2_verdict === "Pass with caution") labels.push("Growth Rate");
  if (row.step4_verdict === "Pass with caution") labels.push("Profitability");
  if (row.step5_verdict === "Pass with caution") labels.push("Debt");
  return labels;
}

// Same buy/hold/sell bucketing ConsensusBanner's distribution bar already
// uses for this data (grades_consensus's "consensus" string, e.g. "Strong
// Buy"/"Buy"/"Hold"/"Sell"/"Strong Sell") -- ConsensusBanner itself doesn't
// color its own rating text, so this is a new mapping, not a shared import.
function ratingColorClass(rating: string): string {
  const normalized = rating.toLowerCase();
  if (normalized.includes("buy")) return "text-positive";
  if (normalized.includes("sell")) return "text-negative";
  if (normalized.includes("hold")) return "text-warn";
  return "text-text-tertiary"; // "N/A"
}

// Column order per design_handoff_fathom_v2/README.md's Watchlist spec:
// Ticker, Sector, Price, Chg, Moat, Valuation, Analysis, Rating, Mkt Cap,
// Beta, P/E, then a trailing icon-only remove button. "Analysis" collapses
// the old F/G/D/P STEP_CHIPS into row.overall_score/overall_verdict, same
// as ScreenerCard's own STEP_CHIPS removal.
export function WatchlistTable({ watchlist, rows, error }: Props) {
  const sorted = useMemo(
    () => (rows ? sortWatchlistRows(rows, watchlist.sort_field as WatchlistSortField, watchlist.sort_direction as SortDirection) : []),
    [rows, watchlist.sort_field, watchlist.sort_direction]
  );

  function openTicker(ticker: string) {
    window.open(`/tickers/${ticker}`, "_blank", "noopener,noreferrer");
  }

  if (watchlist.tickers.length === 0) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6 text-center text-sm text-text-tertiary">
        No tickers in this watchlist yet — add one from its ticker page.
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load this watchlist — {error.message}</p>;
  }

  if (!rows) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  return (
    <div className="rounded-lg border border-border-card bg-surface">
      <Table containerClassName="overflow-x-auto" className="min-w-[900px] border-separate border-spacing-0">
        <TableHeader>
          <TableRow className="border-border-card bg-surface-2 hover:bg-surface-2">
            <TableHead className={`${HEAD_CLASS} w-40`}>Ticker</TableHead>
            <TableHead className={HEAD_CLASS}>Sector</TableHead>
            <TableHead className={`${HEAD_CLASS} text-right`}>Price</TableHead>
            <TableHead className={`${HEAD_CLASS} text-right`}>Chg</TableHead>
            <TableHead className={`${HEAD_CLASS} text-center`}>Moat</TableHead>
            <TableHead className={`${HEAD_CLASS} text-center`}>Valuation</TableHead>
            <TableHead className={`${HEAD_CLASS} text-center`}>Analysis</TableHead>
            <TableHead className={HEAD_CLASS}>Rating</TableHead>
            <TableHead className={`${HEAD_CLASS} text-right`}>Mkt Cap</TableHead>
            <TableHead className={`${HEAD_CLASS} text-right`}>Beta</TableHead>
            <TableHead className={`${HEAD_CLASS} text-right`}>P/E</TableHead>
            <TableHead className="w-9" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow key={row.ticker} onClick={() => openTicker(row.ticker)} className="cursor-pointer border-border-subtle">
              <TableCell className="w-40 max-w-40 overflow-hidden">
                <p className="font-mono text-sm font-bold text-text-primary">{row.ticker}</p>
                <p className="truncate text-xs text-text-tertiary" title={row.company_name ?? undefined}>
                  {row.company_name ?? "—"}
                </p>
              </TableCell>
              <TableCell className="text-text-secondary">{row.sector ?? "—"}</TableCell>
              <TableCell className="text-right font-mono tabular-nums text-text-secondary">
                {row.price != null ? fmtMoney(row.price) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {row.change != null && row.change_percent != null ? (
                  <PriceChange change={row.change} changePercent={row.change_percent} />
                ) : (
                  <span className="text-text-tertiary">—</span>
                )}
              </TableCell>
              <TableCell className="text-center">
                <MoatPill moat={row.moat} variant="flat" />
              </TableCell>
              <TableCell className="text-center">
                <ValuationBadge verdict={row.valuation_verdict} variant="flat" />
              </TableCell>
              <TableCell className="text-center">
                <span
                  className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold ${flatChipClassFor(row.overall_score, row.overall_verdict)}`}
                >
                  {row.overall_score ?? "—"}
                  {row.overall_verdict === "Pass with caution" && (
                    <span title={`Passed with caution: ${cautionStepLabels(row).join(", ")}`}>⚠</span>
                  )}
                </span>
              </TableCell>
              <TableCell className={ratingColorClass(row.consensus_rating)}>{row.consensus_rating}</TableCell>
              <TableCell className="text-right font-mono text-text-secondary">
                {row.market_cap != null ? fmtCompactMoney(row.market_cap) : "—"}
              </TableCell>
              <TableCell className="text-right font-mono text-text-secondary">{row.beta != null ? fmtNumber(row.beta) : "—"}</TableCell>
              <TableCell className="text-right font-mono text-text-secondary">
                {row.pe_ratio != null ? fmtNumber(row.pe_ratio) : "—"}
              </TableCell>
              <TableCell className="text-center">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeTickerFromWatchlist(watchlist.id, row.ticker);
                  }}
                  aria-label={`Remove ${row.ticker}`}
                  title={`Remove ${row.ticker}`}
                  className="inline-flex size-[22px] items-center justify-center rounded-md border border-border-input text-sm leading-none text-text-tertiary transition-colors hover:border-negative hover:text-negative"
                >
                  −
                </button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
