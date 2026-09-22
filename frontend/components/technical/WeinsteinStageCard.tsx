import { ChecklistCard, fmtSwingDate, type ChecklistItem } from "@/components/technical/ChecklistCard";
import {
  formatWeinsteinPendingCushion,
  formatWeinsteinPendingEtaScenario,
  formatWeinsteinSince,
  weinsteinPendingHasCushionEtaDivergence,
  weinsteinUnavailableReason,
  WEINSTEIN_LOWER_BOUND_CAVEAT,
  WEINSTEIN_PENDING_CANCELS_NOT_PAUSES_NOTE,
  WEINSTEIN_PENDING_CUSHION_ETA_DIVERGENCE_NOTE,
  WEINSTEIN_PENDING_NOT_A_PREDICTION_NOTE,
  WEINSTEIN_PENDING_SCENARIO_LABEL,
  WEINSTEIN_PENDING_SCENARIO_ORDER,
  WEINSTEIN_PENDING_TARGET_LABEL,
  WEINSTEIN_STAGE_LABEL,
  WEINSTEIN_STAGE_STYLES_CHIP,
} from "@/lib/weinsteinStage";
import type { TrendAnalysisOut, WeinsteinPendingOut } from "@/lib/api/types";

interface Props {
  data: TrendAnalysisOut;
}

const DISCLAIMER =
  "Classic technical stage-analysis framework (Stan Weinstein); not backtested against Fathom's own criteria the way the Reversal/Trend Continuation checks above are. Informational only, not a trading signal.";

// Two distinct null-stage messages, deliberately not conflated -- see
// lib/weinsteinStage.ts::weinsteinUnavailableReason for the full mechanism.
// "not_yet_computed" makes no claim about the ticker's own history (it may
// well have years of it, just not yet reprocessed under this feature);
// "insufficient_history" is the one case where the original wording is
// actually accurate.
const UNAVAILABLE_MESSAGE: Record<ReturnType<typeof weinsteinUnavailableReason>, string> = {
  not_yet_computed: "Weinstein stage not yet available for this ticker — check back after the next update.",
  insufficient_history: "Insufficient price history for a 30-week stage read yet.",
};

function fmtPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

// "Pending confirmation" + ETA sub-block -- see docs/
// weinstein_pending_confirmation_investigation_2026-09-22.md for the design
// this implements. Styled like TrendContinuationCard's own amber "pullback
// pending" state (the `warn` token), since this is the same shape of
// "not yet, but close" caution reading. Rendered via ChecklistCard's `extra`
// slot, so it appears below the checklist itself, above the disclaimer, only
// when the ticker is currently pending.
function WeinsteinPendingBlock({ pending }: { pending: WeinsteinPendingOut }) {
  const cushionText = formatWeinsteinPendingCushion(pending);
  const hasDivergence = weinsteinPendingHasCushionEtaDivergence(pending);

  return (
    <div className="space-y-2 rounded-md border border-warn/40 bg-warn/10 p-3 text-xs">
      <p className="font-semibold text-warn">Pending {WEINSTEIN_PENDING_TARGET_LABEL[pending.direction]}</p>
      <p className="text-text-secondary">
        {pending.since_date
          ? `Price cleared the band ${formatWeinsteinSince(pending.since_date, pending.since_is_lower_bound, fmtSwingDate).toLowerCase()}, but the 30-week MA slope hasn't turned yet.`
          : "Price has already cleared the band, but the 30-week MA slope hasn't turned yet."}
      </p>
      <ul className="space-y-1">
        {WEINSTEIN_PENDING_SCENARIO_ORDER.map((key) => {
          const scenario = pending.eta[key];
          if (!scenario) return null;
          return (
            <li key={key} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <span className="text-text-secondary">{WEINSTEIN_PENDING_SCENARIO_LABEL[key]}:</span>
              <span className="font-medium text-text-primary">{formatWeinsteinPendingEtaScenario(scenario, fmtSwingDate)}</span>
            </li>
          );
        })}
      </ul>
      {cushionText && <p className="text-text-secondary">{cushionText}</p>}
      {hasDivergence && <p className="text-warn">{WEINSTEIN_PENDING_CUSHION_ETA_DIVERGENCE_NOTE}</p>}
      <p className="text-text-tertiary">
        {WEINSTEIN_PENDING_NOT_A_PREDICTION_NOTE} {WEINSTEIN_PENDING_CANCELS_NOT_PAUSES_NOTE}
      </p>
    </div>
  );
}

export function WeinsteinStageCard({ data }: Props) {
  const stage = data.weinstein_stage;

  if (!stage) {
    const reason = weinsteinUnavailableReason(data.weinstein_weeks_available);
    return (
      <ChecklistCard
        title="Weinstein Stage Analysis"
        statusLabel={reason === "not_yet_computed" ? "Not yet computed" : "Insufficient history"}
        statusToneClass="border-border-card bg-surface-2 text-text-tertiary"
        blurb="30-week moving-average stage classification (Base/Advance/Top/Decline), plus supporting volume and relative-strength context."
        items={[]}
        disclaimer={UNAVAILABLE_MESSAGE[reason]}
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
      detail: data.weinstein_stage_since_date && data.weinstein_stage_since_is_lower_bound ? WEINSTEIN_LOWER_BOUND_CAVEAT : undefined,
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
      extra={data.pending ? <WeinsteinPendingBlock pending={data.pending} /> : undefined}
      disclaimer={DISCLAIMER}
      collapsible
    />
  );
}
