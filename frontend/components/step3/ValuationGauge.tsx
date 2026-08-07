import { fmtMoney, fmtNumber, fmtPct } from "@/lib/format";

interface Props {
  /** Fraction, e.g. -0.218 for -21.8%. Drives both the discount/premium
   * readout and the marker position. */
  discountPremiumPct: number | null;
  intrinsicValuePerShare: number | null;
  lastClose: number | null;
  /** FMP's reportedCurrency (e.g. "TWD") -- null for a USD reporter, in
   * which case no FX caption renders at all. See CLAUDE.md's non-USD
   * currency conversion investigation. */
  reportedCurrency?: string | null;
  /** The reportedCurrency -> USD spot rate actually applied. */
  fxRate?: number | null;
  /** ISO timestamp of when fxRate was fetched. */
  fxRateAsOf?: string | null;
}

function fxCaption(reportedCurrency: string | null | undefined, fxRate: number | null | undefined, fxRateAsOf: string | null | undefined): string | null {
  if (!reportedCurrency || reportedCurrency === "USD") return null;
  if (fxRate == null) return `${reportedCurrency} → USD rate unavailable — Valuation may be incomplete.`;
  const asOf = fxRateAsOf ? new Date(fxRateAsOf).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : null;
  return `Converted from ${reportedCurrency} @ ${fmtNumber(fxRate, 4)}${asOf ? ` (as of ${asOf})` : ""}`;
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

// Horizontal gradient-track gauge per the design handoff's exact spec:
// "8px-tall rounded track, linear-gradient(90deg, green, amber, red), a
// 3x16px white marker with a box-shadow ring matching the card background,
// positioned via left: calc(50% + discountPremium% * 0.7) clamped to
// 3-97%." Replaces the previous circular/needle gauge. Also now owns the
// intrinsic-value headline + discount/premium% + "vs last close" line
// directly above it -- Auto and Manual used to each duplicate that block
// separately; consolidating it here means both columns render identically
// from one component instead of two hand-kept-in-sync copies.
export function ValuationGauge({ discountPremiumPct, intrinsicValuePerShare, lastClose, reportedCurrency, fxRate, fxRateAsOf }: Props) {
  // discountPremiumPct is a fraction (e.g. -0.218) -- the CSS formula in the
  // handoff operates on the percentage number (-21.8), not the fraction.
  const markerLeft = discountPremiumPct != null ? clamp(50 + discountPremiumPct * 100 * 0.7, 3, 97) : null;
  // Negative (a "discount" -- price below intrinsic value) is undervalued,
  // the good/green case; positive ("premium") is overvalued/red. Matches
  // FairValuePill's own undervalued=positive/overvalued=negative mapping.
  const pctClass = discountPremiumPct == null ? "text-text-tertiary" : discountPremiumPct < 0 ? "text-positive" : discountPremiumPct > 0 ? "text-negative" : "text-text-tertiary";
  const caption = fxCaption(reportedCurrency, fxRate, fxRateAsOf);

  return (
    <div className="space-y-3" role="img" aria-label="Intrinsic value vs stock price gauge">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-3xl font-bold tabular-nums text-text-primary">
          {intrinsicValuePerShare != null ? fmtMoney(intrinsicValuePerShare) : "—"}
        </span>
        {discountPremiumPct != null && (
          <span className={`font-mono text-sm font-semibold ${pctClass}`}>{fmtPct(discountPremiumPct * 100, 1)}</span>
        )}
      </div>
      <p className="text-xs text-text-tertiary">vs last close {lastClose != null ? fmtMoney(lastClose) : "—"}</p>
      {caption && <p className="text-xs text-text-tertiary">{caption}</p>}

      <div className="relative pt-2">
        <div
          className="h-2 w-full rounded-full"
          style={{ background: "linear-gradient(90deg, var(--color-positive), var(--color-warn), var(--color-negative))" }}
        />
        {markerLeft != null && (
          <span
            className="absolute top-2 h-4 w-[3px] -translate-x-1/2 rounded-full bg-white"
            style={{ left: `${markerLeft}%`, boxShadow: "0 0 0 3px var(--color-surface)" }}
          />
        )}
      </div>
      <div className="flex justify-between text-[11px] text-text-tertiary">
        <span>Undervalued</span>
        <span>Overvalued</span>
      </div>
    </div>
  );
}
