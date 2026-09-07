import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import { formatWeinsteinSince, WEINSTEIN_STAGE_LABEL, WEINSTEIN_STAGE_STYLES_CHIP, WEINSTEIN_STAGE_STYLES_FLAT, type WeinsteinStage } from "@/lib/weinsteinStage";
import { cn } from "@/lib/utils";
import type { TrendAnalysisOut } from "@/lib/api/types";

// Narrowed to just the 5 fields this pill actually needs, rather than the
// full TrendAnalysisOut -- lets ScreenerCard pass its TickerScoreOut row
// directly (which carries the same 5 denormalized field names/types, see
// CLAUDE.md's Weinstein Screener-surfacing note) with no adapter object,
// since TypeScript structural typing accepts a wider-typed variable
// wherever a narrower shape is expected.
type WeinsteinStagePillData = Pick<
  TrendAnalysisOut,
  "weinstein_stage" | "weinstein_stage_since_date" | "weinstein_stage_since_is_lower_bound" | "weinstein_ma_slope_pct" | "weinstein_vs_ma_pct"
>;

// Screener card: compact "S1"-"S4" text to fit alongside the other 3 pills
// at the narrower card width. Unlike Moat/PerfVsSpy's own "screener" tier
// (which maps every value to the same repeated word, since color alone
// conveys state there), each Weinstein stage gets its own distinct short
// label -- which stage it is is the whole point of this pill.
const LABELS_SCREENER: Record<WeinsteinStage, string> = { base: "S1", advance: "S2", top: "S3", decline: "S4" };

const LABEL_SETS: Record<"full" | "screener", Record<WeinsteinStage, string>> = {
  full: WEINSTEIN_STAGE_LABEL,
  screener: LABELS_SCREENER,
};

interface Props {
  // null (or undefined while loading) renders nothing -- a ticker with too
  // little price history for a 30-week stage read yet isn't "no stage",
  // it's "not computed," and gets no pill at all rather than a placeholder
  // (same "only show when meaningful" contract as MoatPill/SpeculativeGrowthPill).
  data: WeinsteinStagePillData | null | undefined;
  // "chip" (default): bordered pill. "flat": borderless, used in
  // TickerHeader's chip row -- same variant shape as MoatPill/SpeculativeGrowthPill.
  variant?: "chip" | "flat";
  // Which label wording tier to use -- see LABEL_SETS above. Defaults to
  // the full "Stage 2 · Advance"-style wording.
  labelSet?: "full" | "screener";
}

function buildTooltip(data: WeinsteinStagePillData): string {
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

export function WeinsteinStagePill({ data, variant = "chip", labelSet = "full" }: Props) {
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
      {LABEL_SETS[labelSet][stage]}
    </span>
  );
}
