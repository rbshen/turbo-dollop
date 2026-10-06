// Display side of the Review status (backend scoring/review.py decides it; nothing here re-derives it). Labels, tones
// and the tooltip sentences are built from the stored TickerScore row only. The numeric Overall score and the stored
// verdict are untouched by a status.

import type { StatusTone } from "@/components/ui/status";
import type { ConvictionLevel, ReviewHint, ReviewReason, ReviewStatus, TickerScoreOut } from "@/lib/api/types";
import { verdictLabel } from "@/lib/tierColor";

export const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  review_structural: "Review (structural)",
  data_uncertain: "Data uncertain",
  review_unclear: "Review (unclear)",
  review_by_design: "Review (by design)",
};

// Existing tones only (docs/design-system.md, "Review status"): structural is the deeper amber, the rest the lighter
// one. Never `negative`: a Review is not a Fail.
export const REVIEW_STATUS_TONE: Record<ReviewStatus, StatusTone> = {
  review_structural: "caution",
  data_uncertain: "warn",
  review_unclear: "warn",
  review_by_design: "warn",
};

const HINT_LABEL: Record<ReviewHint, string> = {
  structural: REVIEW_STATUS_LABEL.review_structural,
  by_design: REVIEW_STATUS_LABEL.review_by_design,
  unclear: REVIEW_STATUS_LABEL.review_unclear,
};

const STEP_NAME: Record<ReviewReason["step"], string> = { step1: "Financials", step5: "Debt" };

export function reviewStepName(step: ReviewReason["step"]): string {
  return STEP_NAME[step];
}

export function reviewHintLabel(hint: ReviewHint): string {
  return HINT_LABEL[hint];
}

const CONVICTION_LABEL: Record<ConvictionLevel, string> = { high: "high", medium: "medium", low: "low" };

function sentence(text: string): string {
  const trimmed = text.trim().replace(/\.+$/, "");
  return `${trimmed}.`;
}

/** "Overall {score} would read {verdict}. {Step} scored {n} (Fail). {evidence}. Conviction: {c}." plus, for a guarded
 * step, "If the data is confirmed this would read {raw hint}." (with the step named when more than one is guarded). */
export function reviewTooltip(
  score: number | null,
  overallVerdict: string | null,
  reasons: ReviewReason[],
  conviction: ConvictionLevel | null | undefined,
): string {
  const parts: string[] = [];
  if (score != null && overallVerdict) parts.push(`Overall ${score} would read ${verdictLabel(overallVerdict)}.`);
  for (const reason of reasons) {
    parts.push(`${STEP_NAME[reason.step]} scored ${reason.score} (${reason.verdict}).`);
    parts.push(sentence(reason.evidence));
  }
  const guarded = reasons.filter((r) => r.guarded);
  for (const reason of guarded) {
    const who = guarded.length > 1 ? ` (${STEP_NAME[reason.step]})` : "";
    parts.push(`If the data is confirmed this would read ${HINT_LABEL[reason.raw_hint]}${who}.`);
  }
  if (conviction) parts.push(`Conviction: ${CONVICTION_LABEL[conviction]}.`);
  return parts.join(" ");
}

/** The stored fields a surface passes in: a TickerScoreOut, a Watchlist row or a Momentum row all carry them (optional
 * on the row payloads, read as null when absent). */
export type StoredReview = Partial<Pick<TickerScoreOut, "overall_verdict" | "review_status" | "review_reasons" | "conviction">>;

export interface DisplayedReview {
  status: ReviewStatus;
  reasons: ReviewReason[];
  conviction: ConvictionLevel | null;
}

/** The stored review, or null for no status. With `liveVerdict` (the Analysis card, which computes the verdict live from
 * the step endpoints) a stored row whose overall_verdict is not that verdict is stale: nothing is shown rather than a
 * label that may no longer apply. */
export function displayedReview(
  stored: StoredReview | null | undefined,
  liveVerdict?: string | null,
): DisplayedReview | null {
  if (!stored?.review_status || !stored.review_reasons?.length) return null;
  if (liveVerdict !== undefined && stored.overall_verdict !== liveVerdict) return null;
  return { status: stored.review_status, reasons: stored.review_reasons, conviction: stored.conviction ?? null };
}
