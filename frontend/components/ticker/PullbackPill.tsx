import { cn } from "@/lib/utils";
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

// Reuses TrendContinuationCard.tsx's own STATUS_PILL_CLASS palette
// verbatim (warn/positive/negative) so the Screener pill and the Technical
// tab's own badge never drift into two different color readings of the
// same status.
const STYLES_CHIP: Record<RenderableStatus, string> = {
  pending: "border-warn/40 bg-warn/16 text-warn",
  recovered: "border-positive/40 bg-positive/16 text-positive",
  invalidated: "border-negative/40 bg-negative/16 text-negative",
};

const STYLES_FLAT: Record<RenderableStatus, string> = {
  pending: "bg-warn/16 text-warn",
  recovered: "bg-positive/16 text-positive",
  invalidated: "bg-negative/16 text-negative",
};

const TOOLTIP = "Trend continuation / pullback read. Backtested informational read, not a trading signal.";

interface Props {
  status: PullbackStatus | null | undefined;
  // "chip" (default): bordered pill. "flat": borderless, used in
  // ScreenerCard's pill row -- same variant shape as WeinsteinStagePill.
  variant?: "chip" | "flat";
}

export function PullbackPill({ status, variant = "chip" }: Props) {
  if (!status || status === "no_pullback") return null;

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
