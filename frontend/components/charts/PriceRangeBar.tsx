import { cn } from "@/lib/utils";
import { fmtMoney } from "@/lib/format";
import { priceRangeGeometry, type BandPosition } from "@/lib/chartGeometry";

interface Props {
  price: number | null;
  /** null draws the reason instead of the bar. */
  fairValue: number | null;
  /** The verdict band as multiples of fair value (0.9 and 1.1, from the backend). */
  bandLow?: number;
  bandHigh?: number;
  currency?: string;
  /** Why there is no fair value, e.g. "No valuation method applies". */
  unavailableReason?: string | null;
  className?: string;
}

const POSITION_TEXT: Record<BandPosition, string> = {
  below: "below the fair-value band",
  inside: "inside the fair-value band",
  above: "above the fair-value band",
};

function labelShift(pct: number): string {
  return pct < 15 ? "translate-x-0" : pct > 85 ? "-translate-x-full" : "-translate-x-1/2";
}

/** The price against the fair-value band. Everything is neutral: the Valuation pill carries the verdict, this says where the price sits in words. */
export function PriceRangeBar({ price, fairValue, bandLow = 0.9, bandHigh = 1.1, currency = "USD", unavailableReason, className }: Props) {
  if (fairValue === null || fairValue <= 0) {
    return (
      <div className={cn("flex flex-col gap-1 text-xs", className)}>
        <p className="text-text-tertiary">No fair value{unavailableReason ? `: ${unavailableReason}` : ""}</p>
        {price !== null && <p className="text-text-secondary">Price {fmtMoney(price, currency)}</p>}
      </div>
    );
  }
  if (price === null || price <= 0) {
    return (
      <div className={cn("flex flex-col gap-1 text-xs", className)}>
        <p className="text-text-secondary">Fair value {fmtMoney(fairValue, currency)}</p>
        <p className="text-text-tertiary">No price to compare{unavailableReason ? `: ${unavailableReason}` : ""}</p>
      </div>
    );
  }

  const g = priceRangeGeometry(price, fairValue, bandLow, bandHigh);
  const premium = `${Math.abs(g.premiumPct).toFixed(1)}% ${g.premiumPct < 0 ? "below" : "above"} fair value`;
  const sentence = `Price is ${g.premiumPct === 0 ? "at fair value" : premium}, ${POSITION_TEXT[g.position]}`;

  return (
    <div
      role="img"
      aria-label={`Price ${fmtMoney(price, currency)}, fair value ${fmtMoney(fairValue, currency)} (band ${bandLow}x to ${bandHigh}x). ${sentence}.`}
      data-position={g.position}
      className={cn("flex flex-col gap-1.5", className)}
    >
      <div className="relative h-9 pt-5">
        <div className="relative h-2 rounded-full bg-surface-2/60">
          <div
            data-testid="price-band"
            className="absolute inset-y-0 border-x border-border-card bg-surface-2"
            style={{ left: `${g.bandLeftPct}%`, width: `${g.bandWidthPct}%` }}
          />
          <div data-testid="fair-value-tick" className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-full bg-text-secondary" style={{ left: `${g.fairPct}%` }} />
        </div>
        <div className="absolute top-0 h-full" style={{ left: `${g.pricePct}%` }} data-testid="price-marker">
          <span className={cn("absolute top-0 whitespace-nowrap font-mono text-xs tabular-nums text-text-primary", labelShift(g.pricePct))}>
            {fmtMoney(price, currency)}
          </span>
          <span className="absolute bottom-0 top-4 w-1 -translate-x-1/2 rounded-full bg-text-primary" />
        </div>
      </div>
      <div className="flex justify-between gap-2 text-xs text-text-tertiary">
        <span>
          {bandLow}x <span className="font-mono tabular-nums">{fmtMoney(fairValue * bandLow, currency)}</span>
        </span>
        <span>
          Fair value <span className="font-mono tabular-nums">{fmtMoney(fairValue, currency)}</span>
        </span>
        <span>
          {bandHigh}x <span className="font-mono tabular-nums">{fmtMoney(fairValue * bandHigh, currency)}</span>
        </span>
      </div>
      <p className="text-xs text-text-secondary">{sentence}</p>
    </div>
  );
}
