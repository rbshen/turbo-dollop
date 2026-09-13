import { ChecklistCard, fmtSwingDate } from "@/components/technical/ChecklistCard";
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
// "pullbacks resolve within N bars" threshold. Kept as a standalone caption
// (see the render below) even though the Recovered case's own numeric
// freshness fact moved onto the timeline in the Phase 3 restructure --
// this reference-window context still matters independent of WHERE the
// bars count is displayed.
const FRESHNESS_ILLUSTRATIVE_WINDOW_BARS = 21;

export type ResolutionStatus = "NoPullback" | "Pending" | "Recovered" | "Invalidated";

export function resolutionStatus(data: TrendAnalysisOut): ResolutionStatus {
  // A flip to downtrend also clears warning_flag (see state_machine.py), so
  // "downtrend" is the only signal needed to distinguish "the pullback
  // resolved bullishly" from "the trend flipped and superseded it."
  //
  // NOTE (Phase 3 trace, not a behavior change): this branch is not
  // actually reachable via TechnicalTab.tsx's own render path today --
  // lib/technicalCardScope.ts only ever mounts <TrendContinuationCard>
  // when trend_state is "uptrend" (a downtrend renders <ReversalCard>
  // instead, collapsing this card to a muted row). It's exercised directly
  // by this file's own unit tests below, and is left in place rather than
  // removed -- deleting a resolutionStatus branch is a logic change this
  // presentation-only pass was explicitly told not to make.
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
// warning_swing marks the pullback's own start), or the swing that resolved
// a pullback (Recovered). Worded per status so the number is never misread
// as measuring something it doesn't -- in particular, Pending's label
// deliberately does NOT say "since pullback started," since that's
// warning_swing's date, not this one.
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

// The "Right now" section's single status line -- what used to be a static
// ChecklistItem label ("Uptrend pausing — price just missed a new high")
// paired with a met/not-met checkbox. Reworded per Phase 3 review feedback
// (plainer, less alarming for a routine in-trend event) and now varies by
// state instead of staying fixed text next to a crossed-out icon, since a
// healthy uptrend spends most of its life in the "no pullback" state and a
// permanently-present, usually-crossed-out checklist item read as noise.
export function rightNowStatusText(data: TrendAnalysisOut, pullbackInProgress: boolean): string {
  if (data.trend_state !== "uptrend") return "Trend has reversed — no longer tracking a pullback here.";
  return pullbackInProgress ? "Pulled back — hasn't made a new high yet" : "No pullback currently active";
}

export function rightNowDetailText(data: TrendAnalysisOut, pullbackInProgress: boolean): string | null {
  if (pullbackInProgress && data.warning_swing) {
    return `Lower high on ${fmtSwingDate(data.warning_swing.date)} against the established uptrend.`;
  }
  return null;
}

// The NoPullback/Pending freshness fact has no timeline dot to attach to
// (NoPullback has no pullback_history at all; Pending's own
// bars_since_confirmation describes last_confirmed_swing, a point BEFORE
// the pullback even started, not any cycle in the timeline) -- so instead
// of a third, separate "freshness bar" element, it renders as a small
// caption directly under the "Right now" status line above. Recovered is
// deliberately excluded here: its fact IS the timeline's own last dot (see
// PullbackHistoryTimeline below), so folding it in twice would reintroduce
// exactly the duplication this restructure removes.
export function rightNowFreshnessCaption(
  status: ResolutionStatus,
  lastConfirmedSwingDate: string | null,
  bars: number | null
): string | null {
  if (status !== "NoPullback" && status !== "Pending") return null;
  if (lastConfirmedSwingDate == null || bars == null) return null;
  return `${FRESHNESS_LABEL[status]}: ${fmtSwingDate(lastConfirmedSwingDate)} · ${bars} bars ago`;
}

type PullbackHistoryPoint = { kind: "warning" | "resolved"; date: string };

// Flattens pullback_history's {warning_swing, resolving_swing} pairs into a
// single chronological sequence -- two points per cycle, always alternating
// (a cycle only ever exists once it's resolved, see state_machine.py::
// run_state_machine, so there's never a stray unpaired warning point here;
// a still-pending warning is shown separately, via the "Right now" section
// above, not in this timeline).
export function pullbackHistoryPoints(history: TrendAnalysisOut["pullback_history"]): PullbackHistoryPoint[] {
  return history.flatMap((cycle) => [
    { kind: "warning" as const, date: cycle.warning_swing.date },
    { kind: "resolved" as const, date: cycle.resolving_swing.date },
  ]);
}

// "how many times has this happened in the current trend" timeline --
// clearly headed "Past cycles this trend" (see the render below) to
// separate it from the "Right now" section above, per the Phase 3 review
// finding that nothing previously distinguished current vs. historical
// pullback state on this card. Renders nothing for an empty history (no
// pullback has resolved yet this trend -- the common case for a fresh or
// still-clean uptrend), same "only show when meaningful" contract the rest
// of this tab's pills already follow. lastPointFreshnessBars annotates the
// final (Recovered-only) dot with "· N bars ago" instead of a separate
// freshness-bar element duplicating the same date.
function PullbackHistoryTimeline({
  history,
  lastPointFreshnessBars,
}: {
  history: TrendAnalysisOut["pullback_history"];
  lastPointFreshnessBars: number | null;
}) {
  if (history.length === 0) return null;
  const points = pullbackHistoryPoints(history);
  const lastIndex = points.length - 1;

  return (
    <div className="flex items-start overflow-x-auto pb-1">
      {points.map((point, i) => (
        <div key={i} className="flex items-center">
          {i > 0 && <div className="h-px w-4 shrink-0 bg-border-subtle" />}
          <div className="flex shrink-0 flex-col items-center gap-1">
            <span
              className={`h-2 w-2 rounded-full ${point.kind === "warning" ? "bg-warn" : "bg-positive"}`}
              title={point.kind === "warning" ? "Pullback began (lower high)" : "Pullback resolved"}
            />
            <span className="whitespace-nowrap text-[10px] text-text-tertiary">
              {fmtSwingDate(point.date)}
              {i === lastIndex && lastPointFreshnessBars != null ? ` · ${lastPointFreshnessBars} bars ago` : ""}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <p className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">{children}</p>;
}

export function TrendContinuationCard({ data }: Props) {
  const status = resolutionStatus(data);
  const pullbackInProgress = data.trend_state === "uptrend" && data.warning_flag === true;
  const freshnessBars = data.bars_since_confirmation;
  const hasHistory = data.pullback_history.length > 0;

  // A legacy/transient row computed before Phase 2 shipped can read
  // Recovered (pullback_occurred_since_flip was already true) with an
  // empty pullback_history (never computed yet, defaults to [] -- see
  // data/trend_analysis_data.py::_pullback_history_from_json). Without
  // this fallback the freshness fact would silently vanish until the next
  // nightly recompute, since it would otherwise only ever render attached
  // to a timeline dot that doesn't exist yet.
  const recoveredFallbackCaption =
    status === "Recovered" && !hasHistory && data.last_confirmed_swing
      ? `${FRESHNESS_LABEL.Recovered}: ${fmtSwingDate(data.last_confirmed_swing.date)} · ${freshnessBars ?? "—"} bars ago`
      : null;
  const detailText = rightNowDetailText(data, pullbackInProgress);
  const freshnessCaption = rightNowFreshnessCaption(status, data.last_confirmed_swing?.date ?? null, freshnessBars);

  return (
    <ChecklistCard
      title="Pullback recovery"
      statusLabel={STATUS_LABEL[status]}
      statusToneClass={STATUS_PILL_CLASS[status]}
      blurb="Checked because the stock is currently in an uptrend. Looks for whether a recent pullback has resolved bullishly or turned into a real breakdown."
      items={[]}
      extra={
        <div className="space-y-4">
          <div className="space-y-1.5">
            <SectionHeading>Right now</SectionHeading>
            <div className="flex items-start gap-2 text-sm">
              <span
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${pullbackInProgress ? "bg-warn" : "bg-border-subtle"}`}
              />
              <div className="min-w-0 space-y-0.5">
                <p className={pullbackInProgress ? "font-medium text-warn" : "text-text-primary"}>
                  {rightNowStatusText(data, pullbackInProgress)}
                </p>
                {detailText && <p className="text-xs text-text-tertiary">{detailText}</p>}
                {status === "Invalidated" && <p className="text-xs text-text-tertiary">{invalidatedFreshnessText(freshnessBars)}</p>}
                {freshnessCaption && <p className="text-xs text-text-tertiary">{freshnessCaption}</p>}
              </div>
            </div>
          </div>

          {(hasHistory || recoveredFallbackCaption) && (
            <div className="space-y-1.5 border-t border-border-subtle pt-4">
              <SectionHeading>
                Past cycles this trend
                {hasHistory && <span className="normal-case text-text-secondary"> ({data.pullback_history.length})</span>}
              </SectionHeading>
              {hasHistory ? (
                <PullbackHistoryTimeline
                  history={data.pullback_history}
                  lastPointFreshnessBars={status === "Recovered" ? freshnessBars : null}
                />
              ) : (
                <p className="text-xs text-text-tertiary">{recoveredFallbackCaption}</p>
              )}
            </div>
          )}

          {status !== "Invalidated" && (
            <p className="text-[11px] text-text-tertiary">
              Bars-since counts above are illustrative only, against a {FRESHNESS_ILLUSTRATIVE_WINDOW_BARS}-trading-day (~1 month)
              reference window — not a validated threshold.
            </p>
          )}
        </div>
      }
      disclaimer={DISCLAIMER}
    />
  );
}
