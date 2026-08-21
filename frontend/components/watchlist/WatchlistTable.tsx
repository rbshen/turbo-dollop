"use client";

import { useMemo } from "react";

import { MiniBarChart } from "@/components/charts/MiniBarChart";
import { SignalBars } from "@/components/watchlist/SignalBars";
import { MOAT_SIGNAL_COLOR, MOAT_SIGNAL_LEVEL } from "@/components/ticker/MoatPill";
import { STATUS_TO_VERDICT } from "@/components/ticker/PerfVsSpyPill";
import { VERDICT_SIGNAL_COLOR, VERDICT_SIGNAL_LEVEL } from "@/components/ticker/FairValuePill";
import { SPECULATIVE_GROWTH_TEXT_CLASS } from "@/components/ticker/SpeculativeGrowthPill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { WatchlistOut, WatchlistRowOut, WatchlistSortField } from "@/lib/api/types";
import { fmtCompactMoney, fmtNumber } from "@/lib/format";
import type { SortDirection } from "@/lib/screenerFilters";
import { flatChipClassFor } from "@/lib/tierColor";
import { TREND_SIGNAL_COLOR } from "@/lib/trendSignal";
import { cn } from "@/lib/utils";
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

// Trend cell: same MiniBarChart house style as the Financials tab's
// Historical Trends grid (thick bars, no axis, hover tooltip w/ signed
// 2-decimal value), just sized down for a table row. Not sortable -- these
// are a 5-year preview, not a single comparable number, so they're
// deliberately absent from WatchlistSortField/SORT_FIELD_OPTIONS.
function TrendCell({ years, values }: { years: string[]; values: (number | null)[] | null }) {
  if (!values || values.every((v) => v == null)) {
    // Empty box, not a dash -- keeps this cell the same size as a populated
    // one so row height/alignment doesn't shift.
    return <span className="flex h-8 w-16 items-center justify-center" />;
  }
  return (
    <div className="w-16">
      {/* barCategoryGap="24%" (default is 10%; was 12% before the REV/NI/CFO
          column-width reduction that shipped alongside the new TREND column)
          -- narrower w-16 cell needs a proportionally wider gap to keep bars
          from looking like a single solid block; every other MiniBarChart
          caller (Financials tab) keeps the default 10%. */}
      <MiniBarChart categories={years} values={values} valueFormat={fmtCompactMoney} height={32} barCategoryGap="24%" />
    </div>
  );
}

// Column order per design_handoff_fathom_v2/README.md's Watchlist spec:
// Ticker, Sector, Price, Chg, Moat, Valuation, Analysis, Rating, Mkt Cap,
// Beta, P/E, then a trailing icon-only remove button. "Analysis" collapses
// the old F/G/D/P STEP_CHIPS into row.overall_score/overall_verdict, same
// as ScreenerCard's own STEP_CHIPS removal. Price/Chg replaced (2026-08-03)
// with Revenue/Net Income/CFO 5yr mini trend charts -- the live quote they
// required was the one thing on this cache-only page that always hit FMP
// live; see watchlist_data.py's now-removed _live_quote. Trend (added
// alongside the Yahoo-Finance-backed trend-structure feature) sits with the
// other 5-bar-vs-3-bar signal-indicator columns, right after vs SPY -- a
// 5-bar SignalBars reading row.bar_level (1-5) directly, no band mapping
// re-derived on the frontend (see analysis/trend_structure/conviction.py).
// REV/NI/CFO headers shortened and their columns narrowed (w-24 -> w-16) to
// make room for the new Trend column above without widening the table
// further -- CFO's own 3-letter label was already short enough to leave
// unchanged.
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
      <Table containerClassName="overflow-x-auto" className="min-w-[1000px] border-separate border-spacing-0">
        <TableHeader>
          <TableRow className="border-border-card bg-surface-2 hover:bg-surface-2">
            <TableHead className={`${HEAD_CLASS} w-40`}>Ticker</TableHead>
            <TableHead className={`${HEAD_CLASS} w-24`}>Sector</TableHead>
            <TableHead className={`${HEAD_CLASS} w-16 text-center`}>REV</TableHead>
            <TableHead className={`${HEAD_CLASS} w-16 text-center`}>NI</TableHead>
            <TableHead className={`${HEAD_CLASS} w-16 text-center`}>CFO</TableHead>
            <TableHead className={`${HEAD_CLASS} w-16 text-center`}>Moat</TableHead>
            <TableHead className={`${HEAD_CLASS} w-16 text-center`}>Value</TableHead>
            <TableHead className={`${HEAD_CLASS} w-16 text-center`}>vs SPY</TableHead>
            <TableHead className={`${HEAD_CLASS} w-16 text-center`}>Trend</TableHead>
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
                <p
                  className={cn(
                    "font-mono text-sm font-bold",
                    row.speculative_growth_qualifies === true ? SPECULATIVE_GROWTH_TEXT_CLASS : "text-text-primary"
                  )}
                >
                  {row.ticker}
                </p>
                <p
                  className={cn(
                    "truncate text-xs",
                    row.speculative_growth_qualifies === true ? SPECULATIVE_GROWTH_TEXT_CLASS : "text-text-tertiary"
                  )}
                  title={row.company_name ?? undefined}
                >
                  {row.company_name}
                </p>
              </TableCell>
              <TableCell className="w-24 max-w-24 truncate text-text-secondary" title={row.sector ?? undefined}>
                {row.sector}
              </TableCell>
              <TableCell className="text-center">
                <TrendCell years={row.years} values={row.revenue} />
              </TableCell>
              <TableCell className="text-center">
                <TrendCell years={row.years} values={row.net_income} />
              </TableCell>
              <TableCell className="text-center">
                <TrendCell years={row.years} values={row.cfo} />
              </TableCell>
              <TableCell className="text-center">
                {row.moat && <SignalBars level={MOAT_SIGNAL_LEVEL[row.moat]} color={MOAT_SIGNAL_COLOR[row.moat]} />}
              </TableCell>
              <TableCell className="text-center">
                {row.valuation_verdict && (
                  <SignalBars level={VERDICT_SIGNAL_LEVEL[row.valuation_verdict]} color={VERDICT_SIGNAL_COLOR[row.valuation_verdict]} />
                )}
              </TableCell>
              <TableCell className="text-center">
                {row.perf_5y_vs_spy_status && row.perf_5y_vs_spy_status !== "no_data" && (
                  <SignalBars
                    level={VERDICT_SIGNAL_LEVEL[STATUS_TO_VERDICT[row.perf_5y_vs_spy_status]]}
                    color={VERDICT_SIGNAL_COLOR[STATUS_TO_VERDICT[row.perf_5y_vs_spy_status]]}
                  />
                )}
              </TableCell>
              <TableCell className="text-center">
                {row.bar_level != null && <SignalBars level={row.bar_level} color={TREND_SIGNAL_COLOR[row.bar_level]} maxBars={5} />}
              </TableCell>
              <TableCell className="text-center">
                <span
                  className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold ${flatChipClassFor(row.overall_score, row.overall_verdict)}`}
                >
                  {row.overall_score}
                  {row.overall_verdict === "Pass with caution" && (
                    <span title={`Passed with caution: ${cautionStepLabels(row).join(", ")}`}>⚠</span>
                  )}
                </span>
              </TableCell>
              <TableCell className={ratingColorClass(row.consensus_rating)}>{row.consensus_rating.toUpperCase()}</TableCell>
              <TableCell className="text-right font-mono text-text-secondary">
                {row.market_cap != null && fmtCompactMoney(row.market_cap)}
              </TableCell>
              <TableCell className="text-right font-mono text-text-secondary">{row.beta != null && fmtNumber(row.beta)}</TableCell>
              <TableCell className="text-right font-mono text-text-secondary">
                {row.pe_ratio != null && fmtNumber(row.pe_ratio)}
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
