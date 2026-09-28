import { Status, type StatusTone } from "@/components/ui/status";
import { fmtMoney } from "@/lib/format";
import type { ValuationSource } from "@/lib/api/types";

// Reuses the scoring system's own tokens directly (no separate Valuation
// palette) -- a 3-state good/mid/bad read, same as Moat: Overvalued is the
// negative extreme, Undervalued is the positive extreme (one tier stronger
// than a plain Fair Valued), no caution/amber tier applies here. Exported so
// PerfVsSpyPill/ValuationBadge share this one map instead of duplicating it
// (vs-SPY reuses Valuation's own palette by design -- see PerfVsSpyPill's
// own comment).
export const VALUATION_TONE: Record<string, StatusTone> = {
  undervalued: "strong",
  overvalued: "negative",
  fair: "positive",
};

const VERDICT_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fairvalued",
};

// For WatchlistTable's SignalBars cells (Valuation and vs-SPY, the latter
// via PerfVsSpyPill's PERF_VS_SPY_TONE map going through the same verdict
// keys) -- same 3 named tokens as VALUATION_TONE above, just solid
// full-opacity fills (not the Status dot), same rationale as MoatPill's own
// MOAT_SIGNAL_LEVEL/MOAT_SIGNAL_COLOR.
export const VERDICT_SIGNAL_LEVEL: Record<string, 1 | 2 | 3> = {
  overvalued: 1,
  fair: 2,
  undervalued: 3,
};

export const VERDICT_SIGNAL_COLOR: Record<string, string> = {
  overvalued: "bg-negative",
  fair: "bg-positive",
  undervalued: "bg-positive-strong",
};

interface Props {
  verdict: string | null;
  price: number | null;
  /** The currency `price` is denominated in (quote_currency) -- defaults
   * to "USD" so every existing caller stays byte-identical until it's
   * threaded through explicitly. */
  currency?: string;
  /** e.g. "DCF" / "P/B" / "PSG" -- the Step 3 method the price was derived
   * from, shown alongside the verdict so it never reads as a bare,
   * unexplained "Undervalued". */
  method?: string | null;
  /** "custom" marks that this verdict came from an active, user-saved
   * TickerCustomValuation rather than Auto Calculation -- surfaced so a
   * Screener/Watchlist comparison across tickers doesn't silently mix an
   * Auto-derived verdict with a user's own override (see CLAUDE.md's Fork
   * B scope decision). Undefined/"auto"/null all render nothing extra. */
  source?: ValuationSource | null;
  /** FMP's reportedCurrency (e.g. "TWD") -- undefined/null/(equal to
   * `currency`) all render nothing extra. `price` is in `currency` either
   * way (converted server-side to quote_currency, not always USD); this is
   * a compact "converted from X" indicator only -- no rate/timestamp here,
   * that detail lives on the Valuation tab's own caption (see
   * ValuationGauge). */
  reportedCurrency?: string | null;
}

export function FairValuePill({ verdict, price, currency = "USD", method, source, reportedCurrency }: Props) {
  if (!verdict || price == null) return null;
  const tone = VALUATION_TONE[verdict] ?? VALUATION_TONE.fair;
  const label = VERDICT_LABELS[verdict] ?? verdict;

  return (
    <Status tone={tone}>
      {label} ·<span className="font-mono tabular-nums">{fmtMoney(price, currency)}</span>
      {method && <span className="font-normal opacity-70">({method})</span>}
      {source === "custom" && <span className="font-normal opacity-70">· Custom</span>}
      {reportedCurrency && reportedCurrency !== currency && (
        <span className="font-normal opacity-70" title={`Converted from ${reportedCurrency}`}>
          · {reportedCurrency}
        </span>
      )}
    </Status>
  );
}
