import { Status, type StatusTone } from "@/components/ui/status";
import type { TickerScoreOut } from "@/lib/api/types";

type ReversalStatus = NonNullable<TickerScoreOut["reversal_status"]>;
type RenderableStatus = Exclude<ReversalStatus, "not_present">;

// "not_present" renders nothing -- it's the majority state (most
// downtrending tickers have no confirmed divergence yet, and every
// uptrending ticker reads this way too, per the state-machine invariant
// documented in ReversalCard.tsx), so showing a pill for it would clutter
// most cards without flagging anything notable. Same "only show when
// meaningful" contract as MoatPill/WeinsteinStagePill.
const LABEL: Record<RenderableStatus, string> = {
  confirmed: "Reversal",
  confirmed_stale: "Reversal (stale)",
};

// positive (green) for a live confirmed signal, neutral once it's past the
// backtest's own significance window (see ReversalCard.tsx's
// STALE_THRESHOLD_BARS) rather than a fabricated "this is now bad" red.
export const REVERSAL_TONE: Record<RenderableStatus, StatusTone> = {
  confirmed: "positive",
  confirmed_stale: "neutral",
};

const TOOLTIP = "Bullish reversal signal (A/D divergence on a confirmed swing low). Backtested informational read, not a trading signal.";

interface Props {
  status: ReversalStatus | null | undefined;
}

export function ReversalPill({ status }: Props) {
  if (!status || status === "not_present") return null;

  return (
    <Status tone={REVERSAL_TONE[status]} title={TOOLTIP}>
      {LABEL[status]}
    </Status>
  );
}
