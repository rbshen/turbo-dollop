"use client";

import { useMemo } from "react";
import { CaretDown, CaretUp } from "@phosphor-icons/react";

import { MiniBarChart } from "@/components/charts/MiniBarChart";
import { SignalBars } from "@/components/watchlist/SignalBars";
import { MOAT_SIGNAL_COLOR, MOAT_SIGNAL_LEVEL } from "@/components/ticker/MoatPill";
import { VERDICT_SIGNAL_COLOR, VERDICT_SIGNAL_LEVEL } from "@/components/ticker/FairValuePill";
import { SPECULATIVE_GROWTH_TEXT_CLASS } from "@/components/ticker/SpeculativeGrowthPill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SortableField, WatchlistOut, WatchlistRowOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtNumber } from "@/lib/format";
import { flatChipClassFor } from "@/lib/tierColor";
import { cn } from "@/lib/utils";
import { removeTickerFromWatchlist } from "@/lib/hooks/useWatchlists";
import { applyHeaderClick, sortWatchlistRows, type SortRule } from "@/lib/watchlistSort";

interface Props {
  watchlist: WatchlistOut;
  rows: WatchlistRowOut[] | undefined;
  error?: Error;
  sortRules: SortRule[];
  onSortRulesChange: (rules: SortRule[]) => void;
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
// are a 5-year preview, not a single comparable number.
function TrendCell({ years, values }: { years: string[]; values: (number | null)[] | null }) {
  if (!values || values.every((v) => v == null)) {
    // Empty box, not a dash -- keeps this cell the same size as a populated
    // one so row height/alignment doesn't shift.
    return <span className="flex h-8 w-14 items-center justify-center" />;
  }
  return (
    <div className="w-14">
      {/* barCategoryGap="15%" -- close to the default 10% every other
          MiniBarChart caller (Financials tab) uses, chosen over the wider
          24%/32% gaps this cell used previously: at w-14's narrow width a
          wide gap left each bar too thin to read, so this favors thicker
          bars with just a small gap over the wider spacing the column's
          two earlier narrowings had used. */}
      <MiniBarChart categories={years} values={values} valueFormat={fmtCompactMoney} height={32} barCategoryGap="15%" />
    </div>
  );
}

// Click-to-sort column header (2026-09-05 redesign, replacing the old
// page-level <select>/direction-toggle dropdown). Renders `children` as a
// button spanning the header cell -- clicking cycles this column through
// applyHeaderClick's append/flip/remove states (see watchlistSort.ts's own
// comment for the exact rule). The active caret + priority numeral render
// inline after the label; the numeral only appears once 2+ rules are
// active, per spec (a lone active column has nothing to disambiguate).
// Text styling is repeated here (matching HEAD_CLASS) rather than relied
// on via CSS inheritance from the <th>, since a bare <button> element's
// default UA color/text-transform isn't guaranteed to inherit consistently
// across browsers.
function SortableHead({
  field,
  rules,
  onChange,
  className,
  children,
}: {
  field: SortableField;
  rules: SortRule[];
  onChange: (rules: SortRule[]) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const priority = rules.findIndex((r) => r.field === field);
  const active = priority !== -1;
  const direction = active ? rules[priority].direction : null;
  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => onChange(applyHeaderClick(rules, field))}
        className={cn(
          "inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-widest text-text-tertiary transition-colors hover:text-text-primary",
          active && "text-text-primary"
        )}
      >
        {children}
        {active && (direction === "asc" ? <CaretUp size={12} /> : <CaretDown size={12} />)}
        {active && rules.length > 1 && <sup className="text-[9px] font-bold">{priority + 1}</sup>}
      </button>
    </TableHead>
  );
}

// Column order per design_handoff_fathom_v2/README.md's Watchlist spec:
// Ticker, Sector, Price, Chg, Moat, Valuation, Analysis, Rating, Mkt Cap,
// Beta, P/E, then a trailing icon-only remove button. "Analysis" collapses
// the old F/G/D/P STEP_CHIPS into row.overall_score/overall_verdict, same
// as ScreenerCard's own STEP_CHIPS removal. Price/Chg replaced (2026-08-03)
// with Revenue/Net Income/CFO 5yr mini trend charts -- the live quote they
// required was the one thing on this cache-only page that always hit FMP
// live; see watchlist_data.py's now-removed _live_quote. The "vs SPY" 3-bar
// column that used to sit before Analysis was removed (2026-09-05) --
// perf_5y_vs_spy_pct/_status are still fetched, just no longer shown or
// sortable at all (no SortableField entry either, unlike before that
// redesign). The Trend/A-D-Div/SMA technical-indicators cluster (added
// alongside the Yahoo-Finance-backed trend-structure feature) was removed
// from this table entirely on 2026-09-06 -- that data is moving to a
// per-ticker Technical tab instead (see CLAUDE.md's "Trend structure
// analysis (Technical)" section); the underlying TrendAnalysis engine/data
// and GET /api/tickers/{ticker}/trend-analysis endpoint are untouched, only
// this table's display of it is gone. REV/NI/CFO headers stay at their
// narrowed width (w-14) from that build, unchanged. Ticker/Sector widened
// the same day (w-32->w-80, w-24->w-60) to use the horizontal space that
// cluster's removal freed up -- roughly proportional to their prior 4:3
// ratio (the 88 freed Tailwind spacing units split ~50/38 by that ratio,
// rounded down to the nearest whole scale step on each); every other
// column (Moat/Value/Analysis/Rating/Mkt Cap/Beta/P/E) is unchanged.
export function WatchlistTable({ watchlist, rows, error, sortRules, onSortRulesChange }: Props) {
  const sorted = useMemo(() => (rows ? sortWatchlistRows(rows, sortRules) : []), [rows, sortRules]);

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
            <SortableHead field="ticker" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} w-80`}>
              Ticker
            </SortableHead>
            <SortableHead field="sector" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} w-60`}>
              Sector
            </SortableHead>
            <TableHead className={`${HEAD_CLASS} w-14 text-center`}>REV</TableHead>
            <TableHead className={`${HEAD_CLASS} w-14 text-center`}>NI</TableHead>
            <TableHead className={`${HEAD_CLASS} w-14 text-center`}>CFO</TableHead>
            <SortableHead field="moat" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} w-16 text-center`}>
              Moat
            </SortableHead>
            <SortableHead
              field="valuation_verdict"
              rules={sortRules}
              onChange={onSortRulesChange}
              className={`${HEAD_CLASS} w-16 text-center`}
            >
              Value
            </SortableHead>
            <SortableHead field="overall_score" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} text-center`}>
              Analysis
            </SortableHead>
            <SortableHead field="consensus_rating" rules={sortRules} onChange={onSortRulesChange} className={HEAD_CLASS}>
              Rating
            </SortableHead>
            <SortableHead field="market_cap" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} text-right`}>
              Mkt Cap
            </SortableHead>
            <SortableHead field="beta" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} text-right`}>
              Beta
            </SortableHead>
            <SortableHead field="pe_ratio" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} text-right`}>
              P/E
            </SortableHead>
            <TableHead className="w-9" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow key={row.ticker} onClick={() => openTicker(row.ticker)} className="cursor-pointer border-border-subtle">
              <TableCell className="w-80 max-w-80 overflow-hidden">
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
              <TableCell className="w-60 max-w-60 truncate text-text-secondary" title={row.sector ?? undefined}>
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
