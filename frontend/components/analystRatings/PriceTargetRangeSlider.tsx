import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";

interface Props {
  low: number | null;
  avg: number | null;
  high: number | null;
  currentPrice: number | null;
  upsidePct: number | null;
  currency?: string;
}

// Horizontal low->high track with a marker at the average target -- replaces
// the old 3-stat-block (Low/Average/High) layout. The "+X% vs. current"
// figure below is the same calculation PriceTargetsCard always had, just
// relocated here.
export function PriceTargetRangeSlider({ low, avg, high, upsidePct, currency = "USD" }: Props) {
  const hasRange = low != null && avg != null && high != null;
  const markerPct = hasRange && high !== low ? Math.min(100, Math.max(0, ((avg! - low!) / (high! - low!)) * 100)) : 50;

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs uppercase tracking-widest text-text-tertiary">Price Target Range</p>
        {/* h-9 == ConsensusBanner's text-3xl line box, so the bar below lands on the same row as its bar. */}
        <div className="h-9">
          {upsidePct != null ? (
            <p className={`text-sm ${pnlClass(upsidePct)}`}>{fmtPct(upsidePct, 1)} vs. current</p>
          ) : (
            <p className="text-sm text-text-tertiary">Current price unavailable</p>
          )}
        </div>
      </div>

      {hasRange ? (
        <>
          <div className="relative">
            <div
              className="h-2 rounded-full"
              style={{ background: "linear-gradient(90deg, var(--color-negative), var(--color-warn), var(--color-positive))" }}
            />
            <div className="absolute -top-6 -translate-x-1/2" style={{ left: `${markerPct}%` }}>
              <p className="whitespace-nowrap font-mono text-xs font-semibold text-text-primary">{fmtMoney(avg!, currency)}</p>
            </div>
            <div
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand ring-2 ring-surface"
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

    </div>
  );
}
