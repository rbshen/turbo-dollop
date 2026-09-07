import { ChecklistCard, fmtSwingDate, type ChecklistItem } from "@/components/technical/ChecklistCard";
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

export function ReversalCard({ data }: Props) {
  const swing = data.last_confirmed_swing;
  const confirmedLl = swing?.classification === "LL" && (data.magnitude_tier === "confirmed" || data.magnitude_tier === "strong");
  const divergencePresent = reversalStatus(data) === "Confirmed";

  const items: ChecklistItem[] = [
    {
      key: "confirmed-ll",
      label: "Confirmed LL (magnitude tier ≥ confirmed)",
      met: confirmedLl,
      detail: swing
        ? `Most recent confirmed swing: ${swing.classification ?? "unknown"} on ${fmtSwingDate(swing.date)}, ${fmtNumber(swing.ratio, 2)}x ATR (${data.magnitude_tier ?? "—"})`
        : "No confirmed swing yet.",
    },
    {
      key: "ad-divergence",
      label: "A/D bullish divergence present and current",
      met: divergencePresent,
      detail: !confirmedLl
        ? "Only evaluated once a confirmed LL is in place."
        : divergencePresent
          ? "Chaikin Oscillator formed a higher low against the trailing-3 confirmed-LL floor at this swing."
          : "No divergence at the current confirmed LL.",
    },
  ];

  const status = reversalStatus(data);
  const statusToneClass = divergencePresent ? "border-positive/40 bg-positive/16 text-positive" : "border-border-card bg-surface-2 text-text-tertiary";

  return (
    <ChecklistCard
      title="Reversal"
      statusLabel={status}
      statusToneClass={statusToneClass}
      blurb="A confirmed swing low with a supporting Accumulation/Distribution divergence -- a candidate short-term reversal read, not a validated entry signal."
      items={items}
      disclaimer={DISCLAIMER}
    />
  );
}
