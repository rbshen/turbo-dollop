import { Status, type StatusTone } from "@/components/ui/status";
import { MOAT_LABELS, type MoatValue } from "@/lib/overallScore";
import { cn } from "@/lib/utils";

// Reuses the scoring system's own tokens directly (no separate Moat
// palette) -- a 3-state good/mid/bad read, same as Valuation: No Moat is
// the negative extreme, Wide Moat is the positive extreme (one tier
// stronger than Narrow Moat), no caution/amber tier applies here.
export const MOAT_TONE: Record<MoatValue, StatusTone> = {
  wide_moat: "strong",
  narrow_moat: "positive",
  no_moat: "negative",
};

// Retained bordered-chip styling -- still needed for MomentumTable's dense
// table-cell use of the "chip" variant below until that column migrates to
// Badge (design-system session 5b/5c). Not used by any "flat" render path
// any more (that path now goes through Status).
const MOAT_STYLES: Record<MoatValue, string> = {
  wide_moat: "bg-positive-strong/16 text-positive-strong border-positive-strong/40",
  narrow_moat: "bg-positive/16 text-positive border-positive/40",
  no_moat: "bg-negative/16 text-negative border-negative/40",
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
  // "chip" (default): the old bordered-pill rendering, kept ONLY for
  // MomentumTable's dense table-cell column (design-system session 5b/5c
  // moves that to Badge, at which point this variant -- and MOAT_STYLES
  // above -- can be deleted). Every other caller (TickerHeader,
  // ScreenerCard) uses "flat", which renders via the shared Status
  // primitive (design-system session 5a).
  variant?: "chip" | "flat";
  // Which label wording tier to use -- see LABEL_SETS above. Defaults to
  // the full "Wide Moat"/"Narrow Moat"/"No Moat" wording.
  labelSet?: "full" | "watchlist" | "screener";
}

export function MoatPill({ moat, variant = "chip", labelSet = "full" }: Props) {
  if (!moat) return null;

  if (variant === "flat") {
    return <Status tone={MOAT_TONE[moat]}>{LABEL_SETS[labelSet][moat]}</Status>;
  }

  return <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold", MOAT_STYLES[moat])}>{LABEL_SETS[labelSet][moat]}</span>;
}
