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

// Abbreviated labels for space-constrained placements (WatchlistTable's
// Moat column) -- color logic is unaffected by which label set is used.
const MOAT_LABELS_SHORT: Record<MoatValue, string> = {
  wide_moat: "Wide",
  narrow_moat: "Narrow",
  no_moat: "None",
};

interface Props {
  // null (or undefined while loading) renders nothing -- only shown once a
  // moat is actually set (see CLAUDE.md's Economic Moat deviation note),
  // never for the "not set" default state.
  moat: MoatValue | null | undefined;
  // "chip" (default): bordered pill, used in TickerHeader's chip row.
  // "flat": borderless, same height as ScreenerCard's other pills.
  variant?: "chip" | "flat";
  // Use MOAT_LABELS_SHORT ("Wide"/"Narrow"/"None") instead of the full
  // "Wide Moat"/"Narrow Moat"/"No Moat" labels -- WatchlistTable only.
  short?: boolean;
}

export function MoatPill({ moat, variant = "chip", short = false }: Props) {
  if (!moat) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? MOAT_STYLES[moat] : MOAT_STYLES_FLAT[moat]
      )}
    >
      {short ? MOAT_LABELS_SHORT[moat] : MOAT_LABELS[moat]}
    </span>
  );
}
