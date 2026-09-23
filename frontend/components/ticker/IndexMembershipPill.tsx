import { cn } from "@/lib/utils";

// Labels for the three tracked named indices, keyed by the backend's raw
// index_name values (core/models.py::IndexConstituent.index_name) --
// mirrors UniverseSelector.tsx's own sp500/nasdaq/dow label choices so the
// Screener toggle and this pill never disagree on what to call an index.
const INDEX_LABELS: Record<string, string> = {
  sp500: "S&P 500",
  nasdaq: "Nasdaq",
  dow: "Dow 30",
};

// Own distinct token (app/globals.css's --fathom-index-membership, a teal
// validated against every other semantic/chart color in use) -- index
// membership is a fact about the ticker, not a Pass/Fail-style verdict or
// Speculative Growth's violet classification, so it deliberately doesn't
// reuse VERDICT_STYLES/MOAT_STYLES/chart-purple.
const STYLES = "bg-index-membership/16 text-index-membership border-index-membership/40";
const STYLES_FLAT = "bg-index-membership/16 text-index-membership";

interface Props {
  // Empty/undefined renders nothing -- same "only show when meaningful"
  // contract as MoatPill/SpeculativeGrowthPill/PerfVsSpyPill.
  memberships: string[] | null | undefined;
  // "chip" (default): bordered pill. "flat": borderless, used in
  // TickerHeader's chip row -- same variant shape as the other header pills.
  variant?: "chip" | "flat";
}

export function IndexMembershipPill({ memberships, variant = "chip" }: Props) {
  if (!memberships || memberships.length === 0) return null;

  const label = memberships.map((name) => INDEX_LABELS[name] ?? name).join(" · ");

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? STYLES : STYLES_FLAT
      )}
    >
      {label}
    </span>
  );
}
