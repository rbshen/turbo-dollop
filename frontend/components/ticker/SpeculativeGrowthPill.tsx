import { fmtCompactMoney, fmtPct, fmtPlainPct, fmtRatio } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { SpeculativeGrowthOut } from "@/lib/api/types";

// Distinct accent outside the existing red/amber/light-green/dark-green
// Pass/Fail palette -- this is an orthogonal classification, not another
// verdict tier, so it deliberately doesn't reuse VERDICT_STYLES/MOAT_STYLES.
// Reuses the existing chart-purple design token (app/globals.css) rather
// than inventing a new one -- already a violet hue, already used as a
// distinct categorical color by AnalystDistributionBar.tsx.
const STYLES = "bg-chart-purple/16 text-chart-purple border-chart-purple/40";
const STYLES_FLAT = "bg-chart-purple/16 text-chart-purple";

const PSG_REASONABLE_MAX = 1.0;

function buildTooltip(data: SpeculativeGrowthOut): string {
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
    lines.push(`Net income (TTM): ${fmtCompactMoney(data.net_income_ttm)}`);
  }
  return lines.join("\n");
}

interface Props {
  // null (or undefined while loading) renders nothing -- only shown once a
  // ticker actually qualifies, never for a "didn't qualify"/"not applicable"
  // state (same "only show when meaningful" contract as MoatPill/
  // PerfVsSpyPill).
  data: SpeculativeGrowthOut | null | undefined;
  // "chip" (default): bordered pill, used in TickerHeader's chip row.
  // "flat": borderless, same height as ScreenerCard/WatchlistTable's other pills.
  variant?: "chip" | "flat";
}

export function SpeculativeGrowthPill({ data, variant = "chip" }: Props) {
  if (!data || !data.qualifies) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? STYLES : STYLES_FLAT
      )}
      title={buildTooltip(data)}
    >
      Speculative Growth
    </span>
  );
}
