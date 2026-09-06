import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import { formatWeinsteinSince, WEINSTEIN_STAGE_LABEL, WEINSTEIN_STAGE_STYLES_CHIP, WEINSTEIN_STAGE_STYLES_FLAT } from "@/lib/weinsteinStage";
import { cn } from "@/lib/utils";
import type { TrendAnalysisOut } from "@/lib/api/types";

interface Props {
  // null (or undefined while loading) renders nothing -- a ticker with too
  // little price history for a 30-week stage read yet isn't "no stage",
  // it's "not computed," and gets no pill at all rather than a placeholder
  // (same "only show when meaningful" contract as MoatPill/SpeculativeGrowthPill).
  data: TrendAnalysisOut | null | undefined;
  // "chip" (default): bordered pill. "flat": borderless, used in
  // TickerHeader's chip row -- same variant shape as MoatPill/SpeculativeGrowthPill.
  variant?: "chip" | "flat";
}

function buildTooltip(data: TrendAnalysisOut): string {
  const lines: string[] = [];
  if (data.weinstein_stage_since_date) {
    lines.push(formatWeinsteinSince(data.weinstein_stage_since_date, data.weinstein_stage_since_is_lower_bound ?? false, fmtSwingDate));
  }
  if (data.weinstein_ma_slope_pct != null) {
    lines.push(`30-wk MA slope: ${data.weinstein_ma_slope_pct >= 0 ? "+" : ""}${data.weinstein_ma_slope_pct.toFixed(1)}%`);
  }
  if (data.weinstein_vs_ma_pct != null) {
    lines.push(`vs. 30-wk MA: ${data.weinstein_vs_ma_pct >= 0 ? "+" : ""}${data.weinstein_vs_ma_pct.toFixed(1)}%`);
  }
  return lines.join("\n");
}

export function WeinsteinStagePill({ data, variant = "chip" }: Props) {
  if (!data || !data.weinstein_stage) return null;
  const stage = data.weinstein_stage;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? WEINSTEIN_STAGE_STYLES_CHIP[stage] : WEINSTEIN_STAGE_STYLES_FLAT[stage]
      )}
      title={buildTooltip(data)}
    >
      {WEINSTEIN_STAGE_LABEL[stage]}
    </span>
  );
}
