"use client";

import { useMemo, useState } from "react";
import { CaretDown, CaretUp, Check, X } from "@phosphor-icons/react";

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

// Sticky header (2026-09-12, fixed same day -- see the Table wrapper's own
// containerClassName below for what the first version got wrong). This
// table needs its own bounded-height/overflow-auto scroll box, matching
// FinancialsStatementTable/RatiosTable's existing convention, rather than
// trying to stick against the window's own scroll: a `<div>` with only
// `overflow-x-auto` set (no explicit `overflow-y`) doesn't stay a normal,
// non-scrolling wrapper the way it looks like it should -- per the CSS
// overflow spec, mixing `visible` on one axis with anything else on the
// other forces the `visible` axis to compute as `auto` too, so that div
// silently becomes its own (unbounded-height, so never-actually-scrolling)
// vertical scroll container. Sticky positioning then resolves against
// *that* div, not the window -- and since the div's top edge sits right at
// the header's own natural position, `top-12`'s 48px offset was already
// "exceeded" with zero scroll, so the header immediately snapped down 48px
// leaving a permanent blank gap above it, never actually tracking window
// scroll. Fixed by making the container an explicit, bounded two-axis
// scroll box (`max-h-[80vh] overflow-auto`) and stickying at `top-0` within
// it, exactly like FinancialsStatementTable/RatiosTable already do.
// `bg-surface-2` (matching the header row's own background) is required on
// each cell, not just the row, since sticky positioning is applied per-`th`
// -- an unpainted cell would let body rows show through as they scroll
// underneath.
const HEAD_CLASS =
  "sticky top-0 z-20 bg-surface-2 whitespace-nowrap text-xs font-semibold uppercase tracking-widest text-text-tertiary";

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
// the same day (w-32->w-[250px], w-24->w-[250px], an explicit equal-width
// pick rather than a proportional split of the freed space) to use the
// horizontal space that cluster's removal freed up; every other column
// (Moat/Value/Analysis/Rating/Mkt Cap/Beta/P/E) is unchanged.
// idle -> confirming (click −) -> removing (click check) -> idle (mutate()
// flips the row out of `rows` entirely) or error (auto-reverts after 4s).
// Same inline-confirm idiom as AddToWatchlistButton's remove flow and
// WatchlistSettingsForm's delete-confirm, just rendered as two small
// icon buttons instead of "Okay"/"Cancel" text -- this column has no room
// for the full "Remove TICKER from WATCHLIST_NAME?" sentence, so the
// question is carried in each icon's title/aria-label instead.
type RemoveState = "idle" | "confirming" | "removing" | "error";

export function WatchlistTable({ watchlist, rows, error, sortRules, onSortRulesChange }: Props) {
  const sorted = useMemo(() => (rows ? sortWatchlistRows(rows, sortRules) : []), [rows, sortRules]);
  const [removeState, setRemoveState] = useState<Record<string, RemoveState>>({});
  // Keyed by ticker only (no watchlist id) -- reset on every tab switch so a
  // lingering "confirming"/"error" state from a previous watchlist never
  // bleeds onto a same-ticker row in a different one. Adjusted during render
  // ("storing information from previous renders", same pattern
  // app/watchlist/page.tsx's own sortState uses for the same activeId-change
  // reason) rather than a useEffect, which would cause an extra render.
  const [lastWatchlistId, setLastWatchlistId] = useState(watchlist.id);
  if (watchlist.id !== lastWatchlistId) {
    setLastWatchlistId(watchlist.id);
    setRemoveState({});
  }

  async function handleRemoveConfirmed(ticker: string) {
    setRemoveState((prev) => ({ ...prev, [ticker]: "removing" }));
    try {
      await removeTickerFromWatchlist(watchlist.id, ticker);
    } catch {
      setRemoveState((prev) => ({ ...prev, [ticker]: "error" }));
      setTimeout(() => setRemoveState((prev) => ({ ...prev, [ticker]: "idle" })), 4000);
    }
  }

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
      <Table containerClassName="max-h-[80vh] overflow-auto" className="min-w-[1000px] border-separate border-spacing-0">
        <TableHeader>
          <TableRow className="border-border-card bg-surface-2 hover:bg-surface-2">
            <SortableHead field="ticker" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} w-[250px]`}>
              Ticker
            </SortableHead>
            <SortableHead field="sector" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} w-[250px]`}>
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
            <TableHead className={`${HEAD_CLASS} w-9`} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow key={row.ticker} onClick={() => openTicker(row.ticker)} className="cursor-pointer border-border-subtle">
              <TableCell className="w-[250px] max-w-[250px] overflow-hidden">
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
              <TableCell className="w-[250px] max-w-[250px] truncate text-text-secondary" title={row.sector ?? undefined}>
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
                {(removeState[row.ticker] ?? "idle") === "confirming" ? (
                  <div className="flex items-center justify-center gap-1">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveConfirmed(row.ticker);
                      }}
                      aria-label={`Confirm: remove ${row.ticker} from ${watchlist.name}`}
                      title={`Remove ${row.ticker} from ${watchlist.name}?`}
                      className="inline-flex size-[22px] items-center justify-center rounded-md border border-warn/50 text-warn transition-colors hover:border-warn"
                    >
                      <Check size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRemoveState((prev) => ({ ...prev, [row.ticker]: "idle" }));
                      }}
                      aria-label="Cancel"
                      title="Cancel"
                      className="inline-flex size-[22px] items-center justify-center rounded-md border border-border-input text-text-tertiary transition-colors hover:border-brand hover:text-text-secondary"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setRemoveState((prev) => ({ ...prev, [row.ticker]: "confirming" }));
                    }}
                    disabled={removeState[row.ticker] === "removing"}
                    aria-label={`Remove ${row.ticker}`}
                    title={removeState[row.ticker] === "error" ? "Failed to remove — retry" : `Remove ${row.ticker}`}
                    className={cn(
                      "inline-flex size-[22px] items-center justify-center rounded-md border text-sm leading-none transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                      removeState[row.ticker] === "error"
                        ? "border-negative text-negative"
                        : "border-border-input text-text-tertiary hover:border-negative hover:text-negative"
                    )}
                  >
                    −
                  </button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
