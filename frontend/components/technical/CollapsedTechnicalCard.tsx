import { Minus } from "@phosphor-icons/react";

interface Props {
  label: string;
  subline: string;
}

// The out-of-scope twin of whichever of Bullish Reversal / Pullback Recovery
// doesn't apply to the current trend direction -- deliberately NOT a
// ChecklistCard (no status pill, no checklist, no disclaimer): there's
// nothing to check here, just a note on why. Thin outline only, no surface
// fill, and a single content-height row (not a column-stretched sibling) --
// rendered BELOW the active card, a dismissed strip rather than a second
// equal-sized card beside it.
export function CollapsedTechnicalCard({ label, subline }: Props) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border-card px-4 py-2">
      <Minus size={14} className="shrink-0 text-text-tertiary" />
      <p className="min-w-0 text-xs text-text-tertiary">
        <span className="font-medium text-text-secondary">{label}</span>
        <span className="mx-1.5">—</span>
        {subline}
      </p>
    </div>
  );
}
