import { fmtMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

// Reuses the scoring system's own tokens directly (no separate Valuation
// palette) -- a 3-state good/mid/bad read, same as Moat: Overvalued is the
// negative extreme, Undervalued is the positive extreme (one tier stronger
// than a plain Fair Valued), no caution/amber tier applies here.
export const VERDICT_STYLES: Record<string, string> = {
  undervalued: "bg-positive-strong/16 text-positive-strong border-positive-strong/40",
  overvalued: "bg-negative/16 text-negative border-negative/40",
  fair: "bg-positive/16 text-positive border-positive/40",
};

const VERDICT_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fair Valued",
};

// Same borderless colors ValuationBadge/MoatPill use for their "flat"
// variant -- keeps TickerHeader's chip row visually identical to
// ScreenerCard's pill row (no border, same height/rounding). Exported so
// ValuationBadge shares this map instead of duplicating it.
export const FLAT_VERDICT_STYLES: Record<string, string> = {
  undervalued: "bg-positive-strong/16 text-positive-strong",
  overvalued: "bg-negative/16 text-negative",
  fair: "bg-positive/16 text-positive",
};

interface Props {
  verdict: string | null;
  price: number | null;
  /** e.g. "DCF" / "P/B" / "PSG" -- the Step 3 method the price was derived
   * from, shown alongside the verdict so it never reads as a bare,
   * unexplained "Undervalued". */
  method?: string | null;
  // "chip" (default): bordered pill. "flat": borderless, same height as
  // ScreenerCard's other pills (MoatPill's "flat" variant, ValuationBadge).
  variant?: "chip" | "flat";
}

export function FairValuePill({ verdict, price, method, variant = "chip" }: Props) {
  if (!verdict || price == null) return null;
  const cls = variant === "chip" ? (VERDICT_STYLES[verdict] ?? VERDICT_STYLES.fair) : (FLAT_VERDICT_STYLES[verdict] ?? FLAT_VERDICT_STYLES.fair);
  const label = VERDICT_LABELS[verdict] ?? verdict;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        cls
      )}
    >
      {label} ·<span className="font-mono tabular-nums">{fmtMoney(price)}</span>
      {method && <span className="font-normal opacity-70">({method})</span>}
    </span>
  );
}
