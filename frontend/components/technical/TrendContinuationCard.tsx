import { ChecklistCard, fmtSwingDate, type ChecklistItem } from "@/components/technical/ChecklistCard";
import type { TrendAnalysisOut } from "@/lib/api/types";

interface Props {
  data: TrendAnalysisOut;
}

// Backtested (see backend/scripts/bt_signal2_analyze.py and the
// investigation report it produced): waiting for the pullback to resolve
// before re-entering beats holding through it, but that's mechanically
// avoiding the pullback's own drawdown, not a distinct predictive edge --
// requiring an "established" uptrend (strong tier + high persistence +
// trending regime) made this WORSE, not better, so that filter is
// deliberately not part of this checklist. The backtest also found no
// meaningful difference between requiring only a confirmed HL vs. a
// confirmed HL-or-HH to clear the pullback, so this card doesn't add new
// resolution logic -- it just reads warning_flag, which the state machine
// already clears on ANY same-direction ratio>=0.5 swing (HL or HH), per
// CHANGES FROM ORIGINAL SCOPE in the task this shipped under.
const DISCLAIMER =
  "Backtested: timing the resolution beats holding through the pullback, but this reflects avoiding the drawdown itself, not a distinct predictive edge. Informational, not a trading signal.";

// Illustrative only -- matches the 1-month (21 trading day) horizon the
// backtest itself measured forward returns over, not a validated
// "pullbacks resolve within N bars" threshold. See the freshness bar's own
// caption below.
const FRESHNESS_ILLUSTRATIVE_WINDOW_BARS = 21;

type ResolutionStatus = "Pending" | "Resolved" | "Invalidated";

function resolutionStatus(data: TrendAnalysisOut): ResolutionStatus {
  // A flip to downtrend also clears warning_flag (see state_machine.py),
  // so "downtrend" is the only signal available from this latest-snapshot-
  // only model to distinguish "the pullback resolved bullishly" from "the
  // trend flipped and superseded it" -- there's no persisted history of
  // the transition itself to check instead.
  if (data.trend_state === "downtrend") return "Invalidated";
  return data.warning_flag ? "Pending" : "Resolved";
}

const STATUS_TONE: Record<ResolutionStatus, string> = {
  Pending: "text-warn",
  Resolved: "text-positive",
  Invalidated: "text-negative",
};

const STATUS_PILL_CLASS: Record<ResolutionStatus, string> = {
  Pending: "border-warn/40 bg-warn/16 text-warn",
  Resolved: "border-positive/40 bg-positive/16 text-positive",
  Invalidated: "border-negative/40 bg-negative/16 text-negative",
};

const STATUS_LABEL: Record<ResolutionStatus, string> = {
  Pending: "Pullback pending",
  Resolved: "Resolved",
  Invalidated: "Invalidated",
};

export function TrendContinuationCard({ data }: Props) {
  const status = resolutionStatus(data);
  const pullbackInProgress = data.trend_state === "uptrend" && data.warning_flag === true;

  const freshnessBars = data.bars_since_confirmation;
  const freshnessPct = freshnessBars != null ? Math.min(100, (freshnessBars / FRESHNESS_ILLUSTRATIVE_WINDOW_BARS) * 100) : null;

  const items: ChecklistItem[] = [
    {
      key: "pullback-in-progress",
      label: "Uptrend + warning_flag active (pullback in progress)",
      met: pullbackInProgress,
      detail:
        pullbackInProgress && data.warning_swing
          ? `Lower high on ${fmtSwingDate(data.warning_swing.date)} against the established uptrend.`
          : data.trend_state !== "uptrend"
            ? "Current trend state is downtrend."
            : "No pullback warning currently active.",
    },
    {
      key: "resolution-status",
      label: "Resolution status",
      statusText: status,
      toneClass: STATUS_TONE[status],
      detail:
        status === "Pending"
          ? "Clears on the next confirmed higher low or higher high (current state machine behavior)."
          : status === "Resolved"
            ? "Trend continuation confirmed, or no pullback has occurred since the last flip."
            : "Trend flipped to downtrend -- any pending pullback is superseded.",
    },
  ];

  const freshnessBar = (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs text-text-tertiary">
        <span>Bars since last confirmation</span>
        <span className="font-mono tabular-nums text-text-secondary">{freshnessBars ?? "—"}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-surface-2">
        <div
          className="h-1.5 rounded-full bg-brand transition-[width]"
          style={{ width: `${freshnessPct ?? 0}%` }}
        />
      </div>
      <p className="text-[11px] text-text-tertiary">
        Illustrative only, against a {FRESHNESS_ILLUSTRATIVE_WINDOW_BARS}-trading-day (~1 month) reference window — not a validated
        threshold.
      </p>
    </div>
  );

  return (
    <ChecklistCard
      title="Trend Continuation"
      statusLabel={STATUS_LABEL[status]}
      statusToneClass={STATUS_PILL_CLASS[status]}
      blurb="Whether an established uptrend's pullback (a lower high against the prevailing trend) has resolved bullishly or been invalidated."
      items={items}
      extra={freshnessBar}
      disclaimer={DISCLAIMER}
    />
  );
}
