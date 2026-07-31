import { MOAT_LABELS, type MoatValue } from "@/lib/overallScore";
import { cn } from "@/lib/utils";

const MOAT_STYLES: Record<MoatValue, string> = {
  wide_moat: "bg-positive/16 text-positive border-positive/40",
  narrow_moat: "bg-warn/16 text-warn border-warn/40",
  no_moat: "bg-negative/16 text-negative border-negative/40",
};

const MOAT_STYLES_FLAT: Record<MoatValue, string> = {
  wide_moat: "bg-positive/16 text-positive",
  narrow_moat: "bg-warn/16 text-warn",
  no_moat: "bg-negative/16 text-negative",
};

interface Props {
  // null (or undefined while loading) renders nothing -- only shown once a
  // moat is actually set (see CLAUDE.md's Economic Moat deviation note),
  // never for the "not set" default state.
  moat: MoatValue | null | undefined;
  // "chip" (default): bordered pill, used in TickerHeader's chip row.
  // "flat": borderless, same height as ScreenerCard's other pills.
  variant?: "chip" | "flat";
}

export function MoatPill({ moat, variant = "chip" }: Props) {
  if (!moat) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? MOAT_STYLES[moat] : MOAT_STYLES_FLAT[moat]
      )}
    >
      {MOAT_LABELS[moat]}
    </span>
  );
}
