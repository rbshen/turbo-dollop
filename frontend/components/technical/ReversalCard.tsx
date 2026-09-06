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

export function ReversalCard({ data }: Props) {
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

  const status = divergencePresent ? "Confirmed" : "Not present";
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
