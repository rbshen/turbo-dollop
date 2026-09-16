import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";

interface Props {
  low: number | null;
  avg: number | null;
  high: number | null;
  currentPrice: number | null;
  upsidePct: number | null;
  currency?: string;
}

// Marker dot color follows the same sign convention as the "vs. current"
// text (pnlClass) -- just expressed as a background instead of a text
// color, since pnlClass itself only returns text-* classes.
function markerBgClass(upsidePct: number | null): string {
  if (upsidePct == null) return "bg-text-tertiary";
  if (upsidePct > 0.005) return "bg-positive";
  if (upsidePct < -0.005) return "bg-negative";
  return "bg-text-tertiary";
}

// Horizontal low->high track with a marker at the average target -- replaces
// the old 3-stat-block (Low/Average/High) layout. The "+X% vs. current"
// figure below is the same calculation PriceTargetsCard always had, just
// relocated here.
export function PriceTargetRangeSlider({ low, avg, high, currentPrice, upsidePct, currency = "USD" }: Props) {
  const hasRange = low != null && avg != null && high != null;
  const markerPct = hasRange && high !== low ? Math.min(100, Math.max(0, ((avg! - low!) / (high! - low!)) * 100)) : 50;

  return (
    <div className="space-y-4">
      <p className="text-xs uppercase tracking-widest text-text-tertiary">
        Price Target Range
        {currentPrice != null && (
          <span className="normal-case text-text-secondary"> — current price {fmtMoney(currentPrice, currency)}</span>
        )}
      </p>

      {hasRange ? (
        <>
          <div className="relative mt-8 mb-2">
            <div className="h-1.5 rounded-full bg-surface-2" />
            <div className="absolute -top-6 -translate-x-1/2" style={{ left: `${markerPct}%` }}>
              <p className="whitespace-nowrap font-mono text-xs font-semibold text-text-primary">{fmtMoney(avg!, currency)}</p>
            </div>
            <div
              className={`absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface ${markerBgClass(upsidePct)}`}
              style={{ left: `${markerPct}%` }}
            />
          </div>
          <div className="flex justify-between font-mono text-xs text-text-tertiary">
            <span>{fmtMoney(low!, currency)} low</span>
            <span>{fmtMoney(high!, currency)} high</span>
          </div>
        </>
      ) : (
        <p className="text-sm text-text-tertiary">Price target range unavailable</p>
      )}

      <div>
        <p className="text-xs text-text-tertiary">Average</p>
        {upsidePct != null ? (
          <p className={`text-sm ${pnlClass(upsidePct)}`}>{fmtPct(upsidePct, 1)} vs. current</p>
        ) : (
          <p className="text-sm text-text-tertiary">Current price unavailable</p>
        )}
      </div>
    </div>
  );
}
