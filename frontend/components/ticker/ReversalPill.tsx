import { cn } from "@/lib/utils";
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

// Same 3-token palette WeinsteinStagePill/TrendContinuationCard already
// use -- positive (green) for a live confirmed signal, neutral/muted once
// it's past the backtest's own significance window (see ReversalCard.tsx's
// STALE_THRESHOLD_BARS) rather than a fabricated "this is now bad" red.
const STYLES_CHIP: Record<RenderableStatus, string> = {
  confirmed: "border-positive/40 bg-positive/16 text-positive",
  confirmed_stale: "border-border-card bg-surface-2 text-text-tertiary",
};

const STYLES_FLAT: Record<RenderableStatus, string> = {
  confirmed: "bg-positive/16 text-positive",
  confirmed_stale: "bg-surface-2 text-text-tertiary",
};

const TOOLTIP = "Bullish reversal signal (A/D divergence on a confirmed swing low). Backtested informational read, not a trading signal.";

interface Props {
  status: ReversalStatus | null | undefined;
  // "chip" (default): bordered pill. "flat": borderless, used in
  // ScreenerCard's pill row -- same variant shape as WeinsteinStagePill.
  variant?: "chip" | "flat";
}

export function ReversalPill({ status, variant = "chip" }: Props) {
  if (!status || status === "not_present") return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? STYLES_CHIP[status] : STYLES_FLAT[status]
      )}
      title={TOOLTIP}
    >
      {LABEL[status]}
    </span>
  );
}
