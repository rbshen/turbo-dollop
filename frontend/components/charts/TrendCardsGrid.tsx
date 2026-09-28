import { MiniBarChart, type StackedBarSegment } from "@/components/charts/MiniBarChart";

export interface TrendCard {
  key: string;
  label: string;
  years: string[];
  /** Single-series bar values, or (when `segments` is set) the combined
   * per-period total -- drives the headline number and the "has any real
   * data" visibility filter in both modes. */
  values: (number | null)[];
  /** When set, the card renders a stacked bar (e.g. long-term + short-term
   * debt) instead of a single-series bar -- see MiniBarChart's own
   * `segments` prop. `values` above must still be the segments' combined
   * total for this card. */
  segments?: StackedBarSegment[];
  /** Card headline number -- unsigned, table-style (matches every other
   * figure shown elsewhere in the app for this metric). */
  format: (v: number) => string;
  /** Per-bar hover tooltip -- signed, 2-decimal ($X.XXM/B or +X.XX%),
   * distinct from `format` since a tooltip has room to be more precise
   * and a hovered bar can legitimately be a down year. */
  tooltipFormat: (v: number) => string;
}

// The card's headline number is the latest real data point in the series
// -- normally the trailing TTM column (years' own last entry is always the
// literal string "TTM", see step1_data.py/step4_data.py), but falls back
// to the latest real annual figure when TTM itself is null for that
// metric. Returns which period it actually came from so the UI can label
// it honestly rather than always claiming "TTM" even on a fallback.
function latestValue(years: string[], values: (number | null)[]): { value: number; period: string } | null {
  for (let i = values.length - 1; i >= 0; i--) {
    const v = values[i];
    if (v != null) return { value: v, period: years[i] };
  }
  return null;
}

interface Props {
  cards: (TrendCard | null)[];
}

// Shared small-multiple preview-card grid -- used by the Financials tab's
// "Historical Trends" grid (revenue/net income/CFO/FCF/AR/CCC) and the
// Ratios tab's margin/ROE/ROIC trend cards. A card whose caller never
// applies (e.g. a company-type exemption -- see HistoricalTrendsGrid/
// RatioTrendsGrid's own exemption comments) is `null` and is still dropped
// entirely -- there's no metric to show at all for this ticker. A card
// that DOES apply but has no real data point anywhere in its series stays
// visible with an empty-state caption instead, per the shared chart empty
// state convention (a trend card with no data doesn't silently vanish).
const MINI_BAR_CHART_HEIGHT = 64;

export function TrendCardsGrid({ cards }: Props) {
  const applicableCards = cards.filter((c): c is TrendCard => c != null);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {applicableCards.map((card) => {
        const hasData = card.values.some((v) => v != null);
        return (
          <div key={card.key} className="space-y-1 rounded-lg border border-border-card bg-surface p-3">
            <p className="truncate text-[11px] font-medium uppercase tracking-wide text-text-tertiary">{card.label}</p>
            {(() => {
              const latest = latestValue(card.years, card.values);
              return (
                <p className="font-mono text-sm font-semibold text-text-primary">
                  {latest ? card.format(latest.value) : "—"}
                  {latest && <span className="ml-1 text-[10px] font-normal text-text-tertiary">({latest.period})</span>}
                </p>
              );
            })()}
            {hasData ? (
              <MiniBarChart categories={card.years} values={card.values} segments={card.segments} valueFormat={card.tooltipFormat} />
            ) : (
              <div className="flex items-center justify-center" style={{ height: MINI_BAR_CHART_HEIGHT }}>
                <p className="text-[13px] text-text-tertiary">No data for this period</p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
