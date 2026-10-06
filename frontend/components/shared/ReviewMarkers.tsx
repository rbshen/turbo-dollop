import { Flag } from "@phosphor-icons/react";

import { Status } from "@/components/ui/status";
import { displayedReview, REVIEW_STATUS_LABEL, REVIEW_STATUS_TONE, reviewTooltip, type StoredReview } from "@/lib/reviewStatus";
import { cn } from "@/lib/utils";

// How a stored Review status is drawn on the list surfaces (Screener card, Watchlist, Momentum). The label, tone and the
// tooltip sentences all come from lib/reviewStatus.ts, the same helpers the ticker header chip uses; nothing here decides
// or words a status. Both render nothing when the row has no status, and never touch the verdict or score beside them.

interface Props {
  /** The row's own stored fields: the status, its reasons and conviction, and the verdict/score the tooltip quotes. */
  review: StoredReview | null | undefined;
  overallScore: number | null | undefined;
  className?: string;
}

function tooltipOf(review: StoredReview, overallScore: number | null | undefined) {
  const shown = displayedReview(review);
  if (!shown) return null;
  return {
    shown,
    title: reviewTooltip(overallScore ?? null, review.overall_verdict ?? null, shown.reasons, shown.conviction),
  };
}

/** Screener card: a compact status pill (the label) beside the score and verdict badge. */
export function ReviewPill({ review, overallScore, className }: Props) {
  const found = review ? tooltipOf(review, overallScore) : null;
  if (!found) return null;
  return (
    <Status tone={REVIEW_STATUS_TONE[found.shown.status]} size="compact" title={found.title} className={className}>
      {REVIEW_STATUS_LABEL[found.shown.status]}
    </Status>
  );
}

/** Dense tables (Watchlist Analysis cell, Momentum Score cell): an icon-only marker, so the column keeps its width. The
 * label is the accessible name; the same tooltip as the pill is the native title. */
export function ReviewMarker({ review, overallScore, className }: Props) {
  const found = review ? tooltipOf(review, overallScore) : null;
  if (!found) return null;
  const label = REVIEW_STATUS_LABEL[found.shown.status];
  return (
    <span
      title={found.title}
      data-testid="review-marker"
      className={cn("inline-flex shrink-0 items-center", REVIEW_STATUS_TONE[found.shown.status] === "caution" ? "text-caution" : "text-warn", className)}
    >
      <Flag size={12} weight="bold" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}
