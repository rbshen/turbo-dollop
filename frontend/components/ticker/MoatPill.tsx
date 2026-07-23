import { MOAT_LABELS, type MoatValue } from "@/lib/overallScore";
import { cn } from "@/lib/utils";

const MOAT_STYLES: Record<MoatValue, string> = {
  wide_moat: "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  narrow_moat: "bg-amber-900/30 text-amber-300 border-amber-700/40",
  no_moat: "bg-red-900/40 text-red-400 border-red-800/40",
};

interface Props {
  // null (or undefined while loading) renders nothing -- only shown once a
  // moat is actually set (see CLAUDE.md's Economic Moat deviation note),
  // never for the "not set" default state.
  moat: MoatValue | null | undefined;
}

export function MoatPill({ moat }: Props) {
  if (!moat) return null;

  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold", MOAT_STYLES[moat])}>
      {MOAT_LABELS[moat]}
    </span>
  );
}
