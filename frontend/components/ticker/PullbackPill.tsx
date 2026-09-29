import { Status, type StatusTone } from "@/components/ui/status";
import type { TickerScoreOut } from "@/lib/api/types";

type PullbackStatus = NonNullable<TickerScoreOut["pullback_status"]>;
type RenderableStatus = Exclude<PullbackStatus, "no_pullback">;

// "no_pullback" renders nothing -- it's the default, common state for a
// healthy uptrend (see TrendContinuationCard.tsx's own NoPullback tier),
// so showing a pill for it would clutter every uptrending card without
// flagging anything notable. Same "only show when meaningful" contract as
// ReversalPill/MoatPill.
const LABEL: Record<RenderableStatus, string> = {
  pending: "Pullback pending",
  recovered: "Pullback recovered",
  invalidated: "Trend invalidated",
};

// Same tones TrendContinuationCard's own status chip uses, so the Screener
// pill and the Technical tab's badge never drift into two colour readings of
// the same status.
export const PULLBACK_TONE: Record<RenderableStatus, StatusTone> = {
  pending: "warn",
  recovered: "positive",
  invalidated: "negative",
};

const TOOLTIP = "Trend continuation / pullback read. Backtested informational read, not a trading signal.";

interface Props {
  status: PullbackStatus | null | undefined;
}

export function PullbackPill({ status }: Props) {
  if (!status || status === "no_pullback") return null;

  return (
    <Status tone={PULLBACK_TONE[status]} title={TOOLTIP}>
      {LABEL[status]}
    </Status>
  );
}
