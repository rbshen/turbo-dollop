import { ChecklistCard, fmtSwingDate, type ChecklistItem } from "@/components/technical/ChecklistCard";
import { formatWeinsteinSince, WEINSTEIN_STAGE_LABEL, WEINSTEIN_STAGE_STYLES_CHIP } from "@/lib/weinsteinStage";
import type { TrendAnalysisOut } from "@/lib/api/types";

interface Props {
  data: TrendAnalysisOut;
}

const DISCLAIMER =
  "Classic technical stage-analysis framework (Stan Weinstein); not backtested against Fathom's own criteria the way the Reversal/Trend Continuation checks above are. Informational only, not a trading signal.";

function fmtPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export function WeinsteinStageCard({ data }: Props) {
  const stage = data.weinstein_stage;

  if (!stage) {
    return (
      <ChecklistCard
        title="Weinstein Stage Analysis"
        statusLabel="Insufficient history"
        statusToneClass="border-border-card bg-surface-2 text-text-tertiary"
        blurb="30-week moving-average stage classification (Base/Advance/Top/Decline), plus supporting volume and relative-strength context."
        items={[]}
        disclaimer="Insufficient price history for a 30-week stage read yet."
      />
    );
  }

  const items: ChecklistItem[] = [
    {
      key: "since",
      label: "In this stage",
      statusText: data.weinstein_stage_since_date
        ? formatWeinsteinSince(data.weinstein_stage_since_date, data.weinstein_stage_since_is_lower_bound ?? false, fmtSwingDate)
        : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "ma-slope",
      label: "30-week MA slope",
      statusText: data.weinstein_ma_slope_pct != null ? fmtPct(data.weinstein_ma_slope_pct) : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "vs-ma",
      label: "Price vs. 30-week MA",
      statusText: data.weinstein_vs_ma_pct != null ? fmtPct(data.weinstein_vs_ma_pct) : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "volume-ratio",
      label: "Volume vs. 30-week avg",
      statusText: data.weinstein_volume_ratio != null ? `${data.weinstein_volume_ratio.toFixed(2)}x` : "—",
      toneClass: "text-text-tertiary",
    },
    {
      key: "mansfield-rs",
      label: "Mansfield RS vs. S&P 500",
      statusText: data.weinstein_mansfield_rs != null ? fmtPct(data.weinstein_mansfield_rs) : "No benchmark data",
      toneClass: data.weinstein_mansfield_rs != null && data.weinstein_mansfield_rs > 0 ? "text-positive" : "text-text-tertiary",
    },
    {
      key: "breakout-confirmed",
      label: "Breakout confirmed (Stage 2 entry + volume + RS)",
      met: data.weinstein_breakout_confirmed === true,
      detail: "Requires a fresh transition into Stage 2/Advance this week, with volume ≥ 2x the 30-week average and positive relative strength.",
    },
  ];

  return (
    <ChecklistCard
      title="Weinstein Stage Analysis"
      statusLabel={WEINSTEIN_STAGE_LABEL[stage]}
      statusToneClass={WEINSTEIN_STAGE_STYLES_CHIP[stage]}
      blurb="30-week moving-average stage classification (Base/Advance/Top/Decline), plus supporting volume and relative-strength context."
      items={items}
      disclaimer={DISCLAIMER}
    />
  );
}
