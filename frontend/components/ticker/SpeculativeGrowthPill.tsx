import { Status } from "@/components/ui/status";
import { fmtCompactMoney, fmtPct, fmtPlainPct, fmtRatio } from "@/lib/format";
import type { SpeculativeGrowthOut } from "@/lib/api/types";

// Distinct accent outside the existing red/amber/light-green/dark-green
// Pass/Fail palette -- this is an orthogonal classification, not another
// verdict tier, so it deliberately doesn't reuse VALUATION_TONE/MOAT_TONE.
// Reuses Status's own "speculative" tone (chart-purple, app/globals.css)
// rather than inventing a new one -- already a violet hue, already used as
// a distinct categorical color by CurrentDistributionList.tsx.
//
// Exported so ScreenerCard/WatchlistTable can recolor a qualifying
// ticker's symbol/name text without duplicating this class string --
// single source of truth for "what color means Speculative Growth" across
// the pill and both list views.
export const SPECULATIVE_GROWTH_TEXT_CLASS = "text-chart-purple";

const PSG_REASONABLE_MAX = 1.0;

function buildTooltip(data: SpeculativeGrowthOut, currency: string): string {
  const lines: string[] = [];
  if (data.growth_rate_pct != null) {
    lines.push(`Forward growth (${data.growth_basis ?? "n/a"} basis): ${fmtPct(data.growth_rate_pct)}`);
  }
  if (data.trailing_revenue_growth_pct != null) {
    lines.push(`Trailing revenue growth: ${fmtPct(data.trailing_revenue_growth_pct)}`);
  }
  if (data.gross_margin_ttm_pct != null) {
    lines.push(`Gross margin (TTM): ${fmtPlainPct(data.gross_margin_ttm_pct)}`);
  }
  if (data.cfo_recent_direction) {
    lines.push(`CFO trend: ${data.cfo_recent_direction.replace("_", " ")}`);
  }
  if (data.cash_runway_years != null) {
    lines.push(`Cash runway: ${fmtRatio(data.cash_runway_years, 1)} yrs`);
  }
  if (data.psg_ratio != null) {
    const note = data.psg_ratio <= PSG_REASONABLE_MAX ? "reasonable" : "rich";
    lines.push(`PSG: ${fmtRatio(data.psg_ratio)} (${note} vs. the ${PSG_REASONABLE_MAX} reference line)`);
  }
  if (data.price_to_sales_ttm != null) {
    lines.push(`P/S (TTM): ${fmtRatio(data.price_to_sales_ttm)}`);
  }
  if (data.net_income_ttm != null) {
    lines.push(`Net income (TTM): ${fmtCompactMoney(data.net_income_ttm, currency)}`);
  }
  return lines.join("\n");
}

interface Props {
  // null (or undefined while loading) renders nothing -- only shown once a
  // ticker actually qualifies, never for a "didn't qualify"/"not applicable"
  // state (same "only show when meaningful" contract as MoatPill/
  // PerfVsSpyPill).
  data: SpeculativeGrowthOut | null | undefined;
  /** net_income_ttm in the tooltip above is a raw statement figure --
   * reported_currency, not quote_currency (see TickerSummaryOut.reported_
   * currency). Defaults to "USD". */
  currency?: string;
}

export function SpeculativeGrowthPill({ data, currency = "USD" }: Props) {
  if (!data || !data.qualifies) return null;

  return (
    <Status tone="speculative" title={buildTooltip(data, currency)}>
      Speculative growth
    </Status>
  );
}
