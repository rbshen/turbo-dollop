import { Status } from "@/components/ui/status";
import { pillLabel } from "@/lib/tierColor";

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

// Index membership is a fact about the ticker, not a Pass/Fail-style verdict
// or a classification worth a colour of its own, so it's a neutral pill.
export function IndexMembershipPill({ memberships }: Props) {
  if (!memberships || memberships.length === 0) return null;

  return <Status tone="neutral">{pillLabel(memberships.map((name) => INDEX_LABELS[name] ?? name).join(" · "))}</Status>;
}
