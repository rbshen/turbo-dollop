import { Status, type StatusTone } from "@/components/ui/status";
import { MOAT_LABELS, type MoatValue } from "@/lib/overallScore";
import { pillLabel } from "@/lib/tierColor";

// Reuses the scoring system's own tokens directly (no separate Moat
// palette) -- a 3-state good/mid/bad read, same as Valuation: No Moat is
// the negative extreme, Wide Moat is the positive extreme (one tier
// stronger than Narrow Moat), no caution/amber tier applies here. Typed to
// this 3-tone subset (not the full StatusTone) so it's directly assignable
// to Badge's tone prop too -- exported so MomentumTable/WatchlistTable's
// dense Badge cells (design-system session 5a) share this one map instead
// of duplicating it.
export const MOAT_TONE: Record<MoatValue, Extract<StatusTone, "strong" | "positive" | "negative">> = {
  wide_moat: "strong",
  narrow_moat: "positive",
  no_moat: "negative",
};

// Short word for a dense Badge cell (MomentumTable/WatchlistTable) -- one
// word, not the full "Wide Moat"/"Narrow Moat"/"No Moat" wording, and
// distinct per state (unlike the pill's own "screener" tier below, where
// color alone conveys state and every label reads "Moat").
export const MOAT_LABEL_SHORT: Record<MoatValue, string> = {
  wide_moat: "Wide",
  narrow_moat: "Narrow",
  no_moat: "None",
};

// Screener card: state is conveyed by color alone (same pattern as the
// vs-SPY pill's own "screener" tier) -- every status renders the same
// literal text here.
const LABELS_SCREENER: Record<MoatValue, string> = {
  wide_moat: "Moat",
  narrow_moat: "Moat",
  no_moat: "Moat",
};

const LABEL_SETS: Record<"full" | "screener", Record<MoatValue, string>> = {
  full: MOAT_LABELS,
  screener: LABELS_SCREENER,
};

// Hover text: what the rating does to the Overall score (Overall = Steps score x multiplier). Narrow's factor is a setting, so it is
// named rather than quoted.
const MOAT_TITLE: Record<MoatValue, string> = {
  wide_moat: "Wide moat: Overall = Steps score × 1.0",
  narrow_moat: "Narrow moat: Overall = Steps score × the Narrow multiplier (Settings > Economic moat)",
  no_moat: "No moat: Overall = Steps score × 0.70",
};

interface Props {
  // null (or undefined while loading) renders nothing -- only shown once a
  // moat is actually set (see CLAUDE.md's Economic Moat deviation note),
  // never for the "not set" default state.
  moat: MoatValue | null | undefined;
  // Which label wording tier to use -- see LABEL_SETS above. Defaults to
  // the full "Wide Moat"/"Narrow Moat"/"No Moat" wording.
  labelSet?: "full" | "screener";
}

export function MoatPill({ moat, labelSet = "full" }: Props) {
  if (!moat) return null;

  return (
    <Status tone={MOAT_TONE[moat]} title={MOAT_TITLE[moat]}>
      {pillLabel(LABEL_SETS[labelSet][moat])}
    </Status>
  );
}
