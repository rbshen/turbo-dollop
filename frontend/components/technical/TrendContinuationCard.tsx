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

export type ResolutionStatus = "NoPullback" | "Pending" | "Recovered" | "Invalidated";

export function resolutionStatus(data: TrendAnalysisOut): ResolutionStatus {
  // A flip to downtrend also clears warning_flag (see state_machine.py), so
  // "downtrend" is the only signal needed to distinguish "the pullback
  // resolved bullishly" from "the trend flipped and superseded it."
  if (data.trend_state === "downtrend") return "Invalidated";
  if (data.warning_flag) return "Pending";
  // warning_flag=false alone is ambiguous -- it reads the same whether no
  // pullback has ever occurred since the last flip, or one occurred and was
  // already resolved by a later confirming swing. pullback_occurred_since_flip
  // (state_machine.py) is what actually distinguishes them: unlike
  // warning_flag, it's never cleared by a resolving swing, only reset by a
  // genuine flip. Null (a row computed before this field existed) reads the
  // same as false until the next nightly recompute, same convention as
  // ad_bullish_divergence elsewhere on this type.
  return data.pullback_occurred_since_flip === true ? "Recovered" : "NoPullback";
}

const STATUS_PILL_CLASS: Record<ResolutionStatus, string> = {
  NoPullback: "border-border-card bg-surface-2 text-text-tertiary",
  Pending: "border-warn/40 bg-warn/16 text-warn",
  Recovered: "border-positive/40 bg-positive/16 text-positive",
  Invalidated: "border-negative/40 bg-negative/16 text-negative",
};

const STATUS_LABEL: Record<ResolutionStatus, string> = {
  NoPullback: "No pullback",
  Pending: "Pullback pending",
  Recovered: "Recovered",
  Invalidated: "Invalidated",
};

// bars_since_confirmation always counts from last_confirmed_swing -- but
// WHICH swing that is varies by status (state_machine.py): the latest
// same-direction continuation with no pullback involved at all
// (NoPullback), the last continuation BEFORE the current pullback started
// (Pending -- last_confirmed_swing is untouched by a warning firing, only
// warning_swing marks the pullback's own start), the swing that resolved a
// pullback (Recovered), or the swing that flipped the trend (Invalidated,
// handled separately below since it drops the progress-bar framing
// entirely). Worded per status so the number is never misread as measuring
// something it doesn't -- in particular, Pending's label deliberately does
// NOT say "since pullback started," since that's warning_swing's date, not
// this one.
export const FRESHNESS_LABEL: Record<Exclude<ResolutionStatus, "Invalidated">, string> = {
  NoPullback: "Bars since last confirming swing",
  Pending: "Bars since uptrend last confirmed",
  Recovered: "Bars since recovery confirmed",
};

// Invalidated has no progress bar/reference-window framing at all (see the
// render below) -- this is the plain fact line shown instead. last_confirmed_swing
// here IS the confirmed LL that flipped the trend, so this is an accurate,
// simple "how long ago did this happen," not a staleness signal.
export function invalidatedFreshnessText(bars: number | null): string {
  return bars != null ? `Downtrend confirmed ${bars} bars ago.` : "Downtrend confirmation date unavailable.";
}

export function TrendContinuationCard({ data }: Props) {
  const status = resolutionStatus(data);
  const pullbackInProgress = data.trend_state === "uptrend" && data.warning_flag === true;

  const freshnessBars = data.bars_since_confirmation;
  const freshnessPct = freshnessBars != null ? Math.min(100, (freshnessBars / FRESHNESS_ILLUSTRATIVE_WINDOW_BARS) * 100) : null;

  const items: ChecklistItem[] = [
    {
      key: "pullback-in-progress",
      label: "Uptrend pausing — price just missed a new high",
      met: pullbackInProgress,
      detail:
        pullbackInProgress && data.warning_swing
          ? `Lower high on ${fmtSwingDate(data.warning_swing.date)} against the established uptrend.`
          : data.trend_state !== "uptrend"
            ? "Current trend state is downtrend."
            : "No pullback warning currently active.",
    },
  ];

  // Invalidated drops the progress-bar/reference-window framing entirely --
  // that framing (an illustrative comparison against the ~1-month horizon
  // the resolution backtest measured) only means something for an
  // unresolved-or-just-resolved pullback. Once the trend has already
  // flipped, the number isn't a staleness signal to compare against
  // anything -- it's just a plain historical fact.
  const freshnessBar =
    status === "Invalidated" ? (
      <p className="text-xs text-text-tertiary">{invalidatedFreshnessText(freshnessBars)}</p>
    ) : (
      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between text-xs text-text-tertiary">
          <span>{FRESHNESS_LABEL[status]}</span>
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
      title="Pullback recovery"
      statusLabel={STATUS_LABEL[status]}
      statusToneClass={STATUS_PILL_CLASS[status]}
      blurb="Checked because the stock is currently in an uptrend. Looks for whether a recent pullback has resolved bullishly or turned into a real breakdown."
      items={items}
      extra={freshnessBar}
      disclaimer={DISCLAIMER}
    />
  );
}
