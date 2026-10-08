"use client";

import { useMemo } from "react";

import { MiniBarChart } from "@/components/charts/MiniBarChart";
import { MOAT_LABEL_SHORT, MOAT_TONE } from "@/components/ticker/MoatPill";
import { VALUATION_LABEL_SHORT, VALUATION_TONE } from "@/components/ticker/FairValuePill";
import { SPECULATIVE_GROWTH_TEXT_CLASS } from "@/components/ticker/SpeculativeGrowthPill";
import { Badge } from "@/components/ui/badge";
import { HEAD_CLASS, openTickerPage, RemoveCell, SkeletonRows, SortableColumnHead, useRemoveFlow } from "@/components/watchlist/tableParts";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SortableField, WatchlistOut, WatchlistRowOut } from "@/lib/api/types";
import { MOAT_NOT_RATED_NOTE, PASS_THRESHOLD } from "@/lib/overallScore";
import { fmtCompactMoney, fmtMoney, joinNatural, fmtNumber, fmtSignedCompactMoneyTooltip } from "@/lib/format";
import { FAIL_DISPLAY_LABEL, toneForNullable } from "@/lib/tierColor";
import { cn } from "@/lib/utils";
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
// scroll box (`max-h-[70vh] overflow-auto`) and stickying at `top-0` within
// it, exactly like FinancialsStatementTable/RatiosTable already do.
// `bg-page` (2026-09-28: was `bg-surface-2`, matching the design system's
// "sticky headers paint bg-page, not a visible surface fill" rule) is
// required on each cell, not just the row, since sticky positioning is
// applied per-`th` -- an unpainted cell would let body rows show through
// as they scroll underneath.
// HEAD_CLASS (the sticky header cell classes) lives in tableParts.tsx, shared with the ETF table.

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

// The steps below the pass line ("May not pass": score under 70, or a stored Fail verdict), named like cautionStepLabels. These are the
// second reason an Overall reads "Pass with caution" (scoring/overall.py::weak_steps); a null score is not weak (exempt or missing).
function weakStepLabels(row: WatchlistRowOut): string[] {
  const labels: string[] = [];
  const steps: [string, number | null, string | null][] = [
    ["Financials", row.step1_score, row.step1_verdict],
    ["Growth Rate", row.step2_score, row.step2_verdict],
    ["Profitability", row.step4_score, row.step4_verdict],
    ["Debt", row.step5_score, row.step5_verdict],
  ];
  for (const [label, score, verdict] of steps) {
    if (score != null && (verdict === "Fail" || score < PASS_THRESHOLD)) labels.push(label);
  }
  return labels;
}

// Hover text for the Analysis pill: names the cautioned steps and/or the steps that may not pass, and/or says the ticker has no Moat
// rated (it is scored as No moat).
export function overallCellTitle(row: WatchlistRowOut): string | undefined {
  const parts: string[] = [];
  if (row.overall_verdict === "Pass with caution") {
    const cautioned = cautionStepLabels(row);
    const weak = weakStepLabels(row);
    if (cautioned.length > 0) parts.push(`Passed with caution: ${joinNatural(cautioned)}`);
    if (weak.length > 0) parts.push(`${joinNatural(weak)} ${FAIL_DISPLAY_LABEL.toLowerCase()}`);
    if (cautioned.length === 0 && weak.length === 0) parts.push("Passed with caution");
  }
  if (row.moat == null && row.overall_score != null) parts.push(MOAT_NOT_RATED_NOTE);
  return parts.length > 0 ? parts.join(". ") : undefined;
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
function TrendCell({
  years,
  values,
  currency = "USD",
}: {
  years: string[];
  values: (number | null)[] | null;
  currency?: string;
}) {
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
      <MiniBarChart
        categories={years}
        values={values}
        valueFormat={(v) => fmtSignedCompactMoneyTooltip(v, currency)}
        height={32}
        barCategoryGap="15%"
      />
    </div>
  );
}

// Click-to-sort column header (2026-09-05 redesign, replacing the old
// page-level <select>/direction-toggle dropdown; 2026-09-28: rendering
// itself moved to the shared components/ui/sort-header.tsx, used by every
// sortable table app-wide). Clicking cycles this column through
// applyHeaderClick's append/flip/remove states (see watchlistSort.ts's own
// comment for the exact rule). The priority numeral only appears once 2+
// rules are active, per spec (a lone active column has nothing to
// disambiguate). `sort` is threaded onto the <th> itself for aria-sort.
function SortableHead({
  field,
  rules,
  onChange,
  className,
  align,
  children,
}: {
  field: SortableField;
  rules: SortRule[];
  onChange: (rules: SortRule[]) => void;
  className?: string;
  align?: "left" | "right";
  children: React.ReactNode;
}) {
  return (
    <SortableColumnHead
      field={field}
      rules={rules}
      onSort={(f) => onChange(applyHeaderClick(rules, f))}
      className={className}
      align={align}
    >
      {children}
    </SortableColumnHead>
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
// redesign). The Trend/A-D-Div/SMA technical-indicators cluster (from the
// since-removed trend-structure feature) was removed from this table on
// 2026-09-06 and the feature itself later deleted outright. REV/NI/CFO headers stay at their
// narrowed width (w-14) from that build, unchanged. Ticker/Sector were widened
// the same day (w-32->w-[250px], w-24->w-[250px]) to use the space that cluster's removal freed up, then narrowed
// to 150px / 140px on 2026-10-06 (see TICKER_COL below) because that pair made the table wider than the page.
// idle -> confirming (click −) -> removing (click check) -> idle (mutate()
// flips the row out of `rows` entirely) or error (auto-reverts after 4s).
// Same inline-confirm idiom as AddToWatchlistButton's remove flow and
// WatchlistSettingsForm's delete-confirm, just rendered as two small
// icon buttons instead of "Okay"/"Cancel" text -- this column has no room
// for the full "Remove TICKER from WATCHLIST_NAME?" sentence, so the
// question is carried in each icon's title/aria-label instead.
// Ticker, Sector, Last, Rev, NI, CFO, Moat, Value, Analysis, Rating, Mkt cap,
// Beta, P/E, remove -- matches the header row below; used only to span the
// loading skeleton's rows across every column.
const COLUMN_COUNT = 14;

// Ticker / Sector widths (th and td). Narrowed from 250px each on 2026-10-06 so the table fits PageContainer's 1216px
// content width (max-w-7xl minus px-8) with no horizontal scroll: fixed and auto columns now sum to about 1,120px.
// Sector truncates with its full name in the cell's title; the company name under the ticker truncates the same way.
// The max-w on each td is the same number (an auto-layout table only honours truncate with a max-width).
const TICKER_COL = "w-[150px]";
const SECTOR_COL = "w-[140px]";

export function WatchlistTable({ watchlist, rows, error, sortRules, onSortRulesChange }: Props) {
  const sorted = useMemo(() => (rows ? sortWatchlistRows(rows, sortRules) : []), [rows, sortRules]);
  const removeFlow = useRemoveFlow(watchlist.id);

  if (watchlist.tickers.length === 0) {
    return <p className="text-xs text-text-tertiary">No tickers in this watchlist yet — add one from its ticker page.</p>;
  }

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load this watchlist — {error.message}</p>;
  }

  if (!rows) {
    return (
      <Table>
        <TableBody>
          <SkeletonRows columns={COLUMN_COUNT} />
        </TableBody>
      </Table>
    );
  }

  return (
    <Table containerClassName="max-h-[70vh] overflow-auto">
      <TableHeader>
        <TableRow className="h-9">
          <SortableHead field="ticker" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} ${TICKER_COL}`}>
            Ticker
          </SortableHead>
          <SortableHead field="sector" rules={sortRules} onChange={onSortRulesChange} className={`${HEAD_CLASS} ${SECTOR_COL}`}>
            Sector
          </SortableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Last</TableHead>
          <TableHead className={`${HEAD_CLASS} w-14 text-center`}>Rev</TableHead>
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
          <SortableHead
            field="market_cap"
            rules={sortRules}
            onChange={onSortRulesChange}
            align="right"
            className={`${HEAD_CLASS} text-right`}
          >
            Mkt cap
          </SortableHead>
          <SortableHead field="beta" rules={sortRules} onChange={onSortRulesChange} align="right" className={`${HEAD_CLASS} text-right`}>
            Beta
          </SortableHead>
          <SortableHead
            field="pe_ratio"
            rules={sortRules}
            onChange={onSortRulesChange}
            align="right"
            className={`${HEAD_CLASS} text-right`}
          >
            P/E
          </SortableHead>
          <TableHead className={`${HEAD_CLASS} w-9`} />
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((row) => (
          <TableRow key={row.ticker} interactive onClick={() => openTickerPage(row.ticker)}>
            <TableCell className={`${TICKER_COL} max-w-[150px] overflow-hidden`}>
                <p
                  className={cn(
                    "font-mono text-sm font-bold whitespace-nowrap",
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
              <TableCell className={`${SECTOR_COL} max-w-[140px] truncate text-text-secondary`} title={row.sector ?? undefined}>
                {row.sector}
              </TableCell>
              <TableCell className="text-right font-mono text-text-secondary">
                {row.last_price != null && fmtMoney(row.last_price, row.quote_currency ?? "USD")}
              </TableCell>
              <TableCell className="text-center">
                <TrendCell years={row.years} values={row.revenue} currency={row.reported_currency ?? "USD"} />
              </TableCell>
              <TableCell className="text-center">
                <TrendCell years={row.years} values={row.net_income} currency={row.reported_currency ?? "USD"} />
              </TableCell>
              <TableCell className="text-center">
                <TrendCell years={row.years} values={row.cfo} currency={row.reported_currency ?? "USD"} />
              </TableCell>
              <TableCell className="text-center">
                {row.moat && (
                  <Badge size="compact" tone={MOAT_TONE[row.moat]}>
                    {MOAT_LABEL_SHORT[row.moat]}
                  </Badge>
                )}
              </TableCell>
              <TableCell className="text-center">
                {row.valuation_verdict && (
                  <Badge size="compact" tone={VALUATION_TONE[row.valuation_verdict]}>
                    {VALUATION_LABEL_SHORT[row.valuation_verdict]}
                  </Badge>
                )}
              </TableCell>
              <TableCell className="text-center">
                {row.is_etf ? (
                  // A fund has no score: the marker replaces the otherwise-blank cell.
                  <Badge size="compact" tone="neutral" title="Exchange-traded fund -- not scored">
                    ETF
                  </Badge>
                ) : row.overall_score != null ? (
                  <Badge
                    size="compact"
                    tone={toneForNullable(row.overall_score, row.overall_verdict)}
                    title={overallCellTitle(row)}
                  >
                    {row.overall_score}
                    {row.overall_verdict === "Pass with caution" && " ⚠"}
                  </Badge>
                ) : (
                  <Badge size="compact" missing />
                )}
              </TableCell>
              <TableCell className={ratingColorClass(row.consensus_rating)}>
                {/* A fund has no analyst consensus and the backend makes no call for it: a dash, not "N/A". */}
                {row.is_etf ? "—" : row.consensus_rating.toUpperCase()}
              </TableCell>
              <TableCell className="text-right font-mono text-text-secondary">
                {row.market_cap != null && fmtCompactMoney(row.market_cap, row.quote_currency ?? "USD")}
              </TableCell>
              <TableCell className="text-right font-mono text-text-secondary">{row.beta != null && fmtNumber(row.beta)}</TableCell>
              <TableCell className="text-right font-mono text-text-secondary">
                {row.pe_ratio != null && fmtNumber(row.pe_ratio)}
              </TableCell>
              <RemoveCell ticker={row.ticker} watchlistName={watchlist.name} flow={removeFlow} />
            </TableRow>
          ))}
        </TableBody>
      </Table>
  );
}
