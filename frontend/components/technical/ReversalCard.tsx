import { ChecklistCard, DotTimeline, fmtSwingDate, SectionHeading, type ChecklistItem, type TimelineDot } from "@/components/technical/ChecklistCard";
import { fmtNumber } from "@/lib/format";
import type { TrendAnalysisOut } from "@/lib/api/types";

interface Props {
  data: TrendAnalysisOut;
}

// Backtested (see backend/scripts/bt_signal1_analyze.py and the
// investigation report it produced): confirmed LL + current A/D bullish
// divergence has a real but modest ~1-month edge that decays to
// indistinguishable-from-noise by 3-6 months. The "mature prior downtrend"
// persistence filter from the original scope made the ticker-clustered
// edge WEAKER, not stronger, so it's deliberately not part of this
// checklist -- see CHANGES FROM ORIGINAL SCOPE in the task this shipped
// under.
const DISCLAIMER = "Backtested: ~1-month directional edge only, not significant at 3-6 months. Informational, not a trading signal.";

// Illustrative only -- matches THIS card's own backtested edge horizon (see
// DISCLAIMER above: "~1-month directional edge"), not TrendContinuationCard's
// FRESHNESS_ILLUSTRATIVE_WINDOW_BARS reused verbatim, even though the two
// currently happen to share the same 21-trading-day value.
const FRESHNESS_ILLUSTRATIVE_WINDOW_BARS = 21;

// Past this point the backtest's own "not significant at 3-6 months" finding
// is already in force, so the badge itself downgrades (see
// reversalDisplayStatus below) rather than just fading a progress bar next
// to an unchanged "Confirmed" pill.
const STALE_THRESHOLD_BARS = 42;

export type ReversalStatus = "Confirmed" | "Not present";

// Pulled out to a standalone pure function (mirroring TrendContinuationCard's
// own resolutionStatus) so lib/technicalInterpretation.ts's sentence
// generator can read this same status without duplicating the confirmed-LL/
// divergence logic.
//
// Note on state-machine invariants: last_confirmed_swing's classification
// direction always matches the CURRENT trend_state (every code path that
// updates last_confirmed_swing -- a same-direction confirming swing or a
// genuine flip -- only ever does so with a swing whose direction equals the
// trend_state it's setting/confirming; see state_machine.py). So
// classification === "LL" (a bearish-primary swing) can only ever be true
// while trend_state === "downtrend" -- i.e. reversalStatus can only ever
// read "Confirmed" when TrendContinuationCard's resolutionStatus reads
// "Invalidated" (the only downtrend-reachable status). It's never reachable
// alongside NoPullback/Pending/Recovered, which all require an uptrend.
export function reversalStatus(data: TrendAnalysisOut): ReversalStatus {
  const swing = data.last_confirmed_swing;
  const confirmedLl = swing?.classification === "LL" && (data.magnitude_tier === "confirmed" || data.magnitude_tier === "strong");

  // ad_bullish_divergence is already scoped by the engine to the ticker's
  // single most-recent CONFIRMED (ratio >= 1.0) LL swing (see
  // TrendStructureResult's own docstring) -- so gating on confirmedLl here
  // is what actually guarantees "current, not stale," not a literal
  // ad_divergence_swing_date == last_confirmed_swing.date comparison. That
  // literal date check was considered and rejected: ad_divergence_swing_date
  // is the matched Chaikin Oscillator low's own date (within a +/-10-bar
  // window), which coincides with the swing's own date only ~23% of the
  // time in practice (checked empirically against real cached history) --
  // an exact-equality gate would misread a genuine, current divergence as
  // "stale" in the large majority of real cases.
  const divergencePresent = confirmedLl && data.ad_bullish_divergence === true;
  return divergencePresent ? "Confirmed" : "Not present";
}

export type ReversalDisplayStatus = "Confirmed" | "Confirmed (stale)" | "Not present";

// Staleness is purely a DISPLAY concern layered on top of reversalStatus,
// not a redefinition of it -- reversalStatus (and the ReversalStatus type)
// stay exactly as they were, since technicalInterpretation.ts's sentence
// generator relies on that same two-value signal-presence reading
// unchanged (see its own layer3 comment on reversalStatus's invariants).
// This wraps it with bars_since_confirmation to decide whether the badge
// itself should read as stale, without touching what "Confirmed" means
// semantically anywhere else.
export function reversalDisplayStatus(data: TrendAnalysisOut): ReversalDisplayStatus {
  const status = reversalStatus(data);
  if (status !== "Confirmed") return status;
  const bars = data.bars_since_confirmation;
  return bars != null && bars >= STALE_THRESHOLD_BARS ? "Confirmed (stale)" : "Confirmed";
}

// The freshness bar's caption, worded per the same three ranges the bar/
// badge themselves key off of -- fresh (still inside the backtest's own
// ~1-month edge window), aged (past that window but not yet past the
// stale threshold), and stale (badge already downgraded).
export function reversalFreshnessCaption(bars: number | null): string {
  if (bars == null || bars < FRESHNESS_ILLUSTRATIVE_WINDOW_BARS) {
    return `Illustrative only, against a ${FRESHNESS_ILLUSTRATIVE_WINDOW_BARS}-trading-day (~1 month) reference window — not a validated threshold.`;
  }
  if (bars < STALE_THRESHOLD_BARS) {
    return "Past the ~1-month edge window this signal was backtested over — still within reporting range, but likely no longer fresh.";
  }
  return "Past 2 months since the confirming low — the backtest found no real edge this far out, so this reading is now flagged stale.";
}

// Turns reversal_history into DotTimeline's own shape -- pulled out to a
// standalone pure function (mirroring TrendContinuationCard's own
// pullbackHistoryPoints) so it's directly unit-testable without rendering.
// Every confirmed LL is its OWN single-point event (not a warning/
// resolution PAIR like pullback_history), so each dot is colored by that
// swing's own ad_bullish_divergence rather than alternating between two
// fixed kinds.
export function reversalHistoryDots(history: TrendAnalysisOut["reversal_history"]): TimelineDot[] {
  return history.map((candidate, i) => ({
    key: `${candidate.swing.date}-${i}`,
    date: candidate.swing.date,
    dotClassName: candidate.ad_bullish_divergence ? "bg-positive" : "bg-border-subtle",
    title: candidate.ad_bullish_divergence ? "Confirmed low — A/D bullish divergence present" : "Confirmed low — no divergence",
  }));
}

// "how many confirmed lows has this downtrend produced" timeline -- headed
// "Past candidates this trend" (see the render below), mirroring
// TrendContinuationCard's own "Past cycles this trend" section. Renders
// nothing for an empty history (DotTimeline's own contract) -- should be
// rare now that a fresh downtrend's flip-triggering LL always seeds
// reversal_history, but a legacy row computed before this field existed
// still reads as [] until its next nightly recompute.
function ReversalHistoryTimeline({ history }: { history: TrendAnalysisOut["reversal_history"] }) {
  return <DotTimeline dots={reversalHistoryDots(history)} />;
}

export function ReversalCard({ data }: Props) {
  const swing = data.last_confirmed_swing;
  const confirmedLl = swing?.classification === "LL" && (data.magnitude_tier === "confirmed" || data.magnitude_tier === "strong");
  const divergencePresent = reversalStatus(data) === "Confirmed";

  const items: ChecklistItem[] = [
    {
      key: "confirmed-ll",
      label: "Solid new low reached",
      met: confirmedLl,
      detail: swing
        ? `Confirmed LL (magnitude tier ≥ confirmed) — Most recent confirmed swing: ${swing.classification ?? "unknown"} on ${fmtSwingDate(swing.date)}, ${fmtNumber(swing.ratio, 2)}x ATR (${data.magnitude_tier ?? "—"})`
        : "Confirmed LL (magnitude tier ≥ confirmed) — No confirmed swing yet.",
    },
    {
      key: "ad-divergence",
      label: "Quiet buying pressure building",
      met: divergencePresent,
      detail: `A/D bullish divergence present and current — ${
        !confirmedLl
          ? "Only evaluated once a confirmed LL is in place."
          : divergencePresent
            ? "Chaikin Oscillator formed a higher low against the trailing-3 confirmed-LL floor at this swing."
            : "No divergence at the current confirmed LL."
      }`,
    },
  ];

  const displayStatus = reversalDisplayStatus(data);
  const statusToneClass =
    displayStatus === "Confirmed" ? "border-positive/40 bg-positive/16 text-positive" : "border-border-card bg-surface-2 text-text-tertiary";

  const bars = data.bars_since_confirmation;
  const freshnessPct = bars != null ? Math.min(100, (bars / FRESHNESS_ILLUSTRATIVE_WINDOW_BARS) * 100) : null;

  // Only rendered once there's a current confirmed reversal signal to
  // measure the age of at all -- divergencePresent, not displayStatus,
  // since the bar/caption are exactly what explain WHY the badge above may
  // already read "(stale)", so they must still render in that case too.
  const freshnessBar = divergencePresent ? (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs text-text-tertiary">
        <span>Bars since confirmed low</span>
        <span className="font-mono tabular-nums text-text-secondary">{bars ?? "—"}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-surface-2">
        <div className="h-1.5 rounded-full bg-brand transition-[width]" style={{ width: `${freshnessPct ?? 0}%` }} />
      </div>
      <p className="text-[11px] text-text-tertiary">{reversalFreshnessCaption(bars)}</p>
    </div>
  ) : null;

  const hasHistory = data.reversal_history.length > 0;
  const historySection = hasHistory ? (
    <div className={`space-y-1.5 ${freshnessBar ? "border-t border-border-subtle pt-4" : ""}`}>
      <SectionHeading>
        Past candidates this trend <span className="normal-case text-text-secondary">({data.reversal_history.length})</span>
      </SectionHeading>
      <ReversalHistoryTimeline history={data.reversal_history} />
    </div>
  ) : null;

  const extra =
    freshnessBar || historySection ? (
      <div className="space-y-4">
        {freshnessBar}
        {historySection}
      </div>
    ) : undefined;

  return (
    <ChecklistCard
      title="Bullish reversal"
      statusLabel={displayStatus}
      statusToneClass={statusToneClass}
      blurb="Checked because the stock is currently in a downtrend. Looks for a solid new low plus quiet buying pressure underneath."
      items={items}
      extra={extra}
      disclaimer={DISCLAIMER}
    />
  );
}
