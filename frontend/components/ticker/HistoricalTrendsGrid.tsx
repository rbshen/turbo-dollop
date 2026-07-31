"use client";

import { MiniBarChart } from "@/components/charts/MiniBarChart";
import { useStep1 } from "@/lib/hooks/useStep1";
import { useStep4 } from "@/lib/hooks/useStep4";
import { fmtCompactMoney, fmtDays, fmtPct, fmtPlainPct, fmtTableMoney } from "@/lib/format";

interface Props {
  ticker: string;
}

interface TrendCard {
  key: string;
  label: string;
  years: string[];
  values: (number | null)[];
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

// The 11-metric "Historical Trends" grid at the top of the Financials
// tab -- sources straight from the same raw Step1/Step4 series
// (revenue/net income/CFO/FCF/margins, ROE/ROIC/AR/CCC) that back the
// Analysis tab's own scoring, just re-surfaced here as small preview
// cards. No new data.
export function HistoricalTrendsGrid({ ticker }: Props) {
  const step1 = useStep1(ticker);
  const step4 = useStep4(ticker);

  if (!step1.data || !step4.data) {
    return <div className="h-24 animate-pulse rounded-lg border border-border-card bg-surface" />;
  }

  const s1 = step1.data;
  const s4 = step4.data;

  const ccc2 = (v: number) => fmtDays(v, 2);

  const cards: (TrendCard | null)[] = [
    { key: "cfo", label: "Net Operating Cash Flow", years: s1.years, values: s1.cfo ?? [], format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "net_income", label: "Net Income", years: s1.years, values: s1.net_income, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "operating_income", label: "Operating Income", years: s1.years, values: s1.operating_income, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "revenue", label: s1.revenue_label, years: s1.years, values: s1.revenue, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "fcf", label: "Free Cash Flow", years: s1.years, values: s1.fcf ?? [], format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "gross_margin", label: "Gross Profit Margin", years: s1.years, values: s1.gross_margin, format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "net_margin", label: "Net Profit Margin", years: s1.years, values: s1.net_margin, format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "roe", label: "ROE", years: s4.years, values: s4.roe, format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "roic", label: "ROIC", years: s4.years, values: s4.roic ?? [], format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "accounts_receivable", label: "Accounts Receivable", years: s4.years, values: s4.accounts_receivable, format: fmtTableMoney, tooltipFormat: fmtCompactMoney },
    { key: "ccc", label: "Cash Conversion Cycle", years: s4.years, values: s4.ccc ?? [], format: (v: number) => fmtDays(v, 0), tooltipFormat: ccc2 },
  ].map((c) => (c.values.some((v) => v != null) ? c : null));

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {cards.map((card) =>
        card ? (
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
            <MiniBarChart categories={card.years} values={card.values} valueFormat={card.tooltipFormat} />
          </div>
        ) : null
      )}
    </div>
  );
}
