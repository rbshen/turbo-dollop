import { Status } from "@/components/ui/status";

// Labels for the three tracked named indices, keyed by the backend's raw
// index_name values (core/models.py::IndexConstituent.index_name) --
// mirrors UniverseSelector.tsx's own sp500/nasdaq/dow label choices so the
// Screener toggle and this pill never disagree on what to call an index.
const INDEX_LABELS: Record<string, string> = {
  sp500: "S&P 500",
  nasdaq: "Nasdaq",
  dow: "Dow 30",
};

interface Props {
  // Empty/undefined renders nothing -- same "only show when meaningful"
  // contract as MoatPill/SpeculativeGrowthPill/PerfVsSpyPill.
  memberships: string[] | null | undefined;
}

// Own distinct pill tone ("index", app/globals.css's --fathom-index-membership,
// a teal validated against every other semantic/chart color in use) --
// index membership is a fact about the ticker, not a Pass/Fail-style verdict
// or Speculative Growth's violet classification, so it deliberately doesn't
// reuse a verdict tone. Otherwise the same pill as every other status.
export function IndexMembershipPill({ memberships }: Props) {
  if (!memberships || memberships.length === 0) return null;

  return <Status tone="index">{memberships.map((name) => INDEX_LABELS[name] ?? name).join(" · ")}</Status>;
}
