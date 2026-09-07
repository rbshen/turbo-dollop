import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import { formatWeinsteinSince, weinsteinUnavailableReason, WEINSTEIN_STAGE_LABEL, WEINSTEIN_STAGE_TEXT_CLASS } from "@/lib/weinsteinStage";
import type { TrendAnalysisOut } from "@/lib/api/types";

interface Props {
  data: TrendAnalysisOut;
}

// Same two null-stage messages as WeinsteinStageCard's own (deliberately not
// shared/exported from there -- this is a short, compact-card variant, not a
// reuse of that card's longer wording).
const UNAVAILABLE_MESSAGE: Record<ReturnType<typeof weinsteinUnavailableReason>, string> = {
  not_yet_computed: "Not yet available — check back after the next update.",
  insufficient_history: "Insufficient price history for a stage read yet.",
};

// Compact companion to Near-term, sitting beside it in the tab's top summary
// row -- the same Weinstein stage/since data the full Weinstein Stage
// Analysis checklist card (further down the page) shows in detail, condensed
// to just the headline read. That fuller card is untouched by this: MA
// slope/volume/relative-strength context still only lives there.
export function LongTermCard({ data }: Props) {
  const stage = data.weinstein_stage;

  return (
    <div className="space-y-2 rounded-lg border border-border-card bg-surface p-6">
      <p className="text-sm text-text-secondary">Long-term (weekly)</p>
      {stage ? (
        <>
          <p className={`text-lg font-semibold ${WEINSTEIN_STAGE_TEXT_CLASS[stage]}`}>{WEINSTEIN_STAGE_LABEL[stage]}</p>
          <p className="text-sm text-text-tertiary">
            {data.weinstein_stage_since_date
              ? formatWeinsteinSince(data.weinstein_stage_since_date, data.weinstein_stage_since_is_lower_bound ?? false, fmtSwingDate)
              : "—"}
          </p>
        </>
      ) : (
        <p className="text-sm text-text-tertiary">{UNAVAILABLE_MESSAGE[weinsteinUnavailableReason(data.weinstein_weeks_available)]}</p>
      )}
    </div>
  );
}
