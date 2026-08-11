import { MOAT_LABELS, type MoatValue } from "@/lib/overallScore";
import { cn } from "@/lib/utils";

// Reuses the scoring system's own tokens directly (no separate Moat
// palette) -- a 3-state good/mid/bad read, same as Valuation: No Moat is
// the negative extreme, Wide Moat is the positive extreme (one tier
// stronger than Narrow Moat), no caution/amber tier applies here.
const MOAT_STYLES: Record<MoatValue, string> = {
  wide_moat: "bg-positive-strong/16 text-positive-strong border-positive-strong/40",
  narrow_moat: "bg-positive/16 text-positive border-positive/40",
  no_moat: "bg-negative/16 text-negative border-negative/40",
};

const MOAT_STYLES_FLAT: Record<MoatValue, string> = {
  wide_moat: "bg-positive-strong/16 text-positive-strong",
  narrow_moat: "bg-positive/16 text-positive",
  no_moat: "bg-negative/16 text-negative",
};

// For WatchlistTable's SignalBars trial -- same 3 named tokens as
// MOAT_STYLES above, just solid full-opacity fills (not the /16
// translucent badge background) since a small bar and a text-badge
// background are different use cases drawing from the same token family.
export const MOAT_SIGNAL_LEVEL: Record<MoatValue, 1 | 2 | 3> = {
  no_moat: 1,
  narrow_moat: 2,
  wide_moat: 3,
};

export const MOAT_SIGNAL_COLOR: Record<MoatValue, string> = {
  no_moat: "bg-negative",
  narrow_moat: "bg-positive",
  wide_moat: "bg-positive-strong",
};

// Watchlist column: state is conveyed by color alone (same pattern as the
// "screener" tier below) -- every status renders the same literal text
// here, just a single letter for this especially dense column.
const LABELS_WATCHLIST: Record<MoatValue, string> = {
  wide_moat: "M",
  narrow_moat: "M",
  no_moat: "M",
};

// Screener card: state is conveyed by color alone (same pattern as the
// vs-SPY pill's own "screener" tier) -- every status renders the same
// literal text here.
const LABELS_SCREENER: Record<MoatValue, string> = {
  wide_moat: "Moat",
  narrow_moat: "Moat",
  no_moat: "Moat",
};

const LABEL_SETS: Record<"full" | "watchlist" | "screener", Record<MoatValue, string>> = {
  full: MOAT_LABELS,
  watchlist: LABELS_WATCHLIST,
  screener: LABELS_SCREENER,
};

interface Props {
  // null (or undefined while loading) renders nothing -- only shown once a
  // moat is actually set (see CLAUDE.md's Economic Moat deviation note),
  // never for the "not set" default state.
  moat: MoatValue | null | undefined;
  // "chip" (default): bordered pill, used in TickerHeader's chip row.
  // "flat": borderless, same height as ScreenerCard's other pills.
  variant?: "chip" | "flat";
  // Which label wording tier to use -- see LABEL_SETS above. Defaults to
  // the full "Wide Moat"/"Narrow Moat"/"No Moat" wording.
  labelSet?: "full" | "watchlist" | "screener";
}

export function MoatPill({ moat, variant = "chip", labelSet = "full" }: Props) {
  if (!moat) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? MOAT_STYLES[moat] : MOAT_STYLES_FLAT[moat]
      )}
    >
      {LABEL_SETS[labelSet][moat]}
    </span>
  );
}
