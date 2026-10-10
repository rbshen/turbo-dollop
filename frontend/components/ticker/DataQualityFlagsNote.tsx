"use client";

import { Info } from "@phosphor-icons/react";

import { noteLines } from "@/lib/dataQualityFlags";
import { useTickerDataQuality } from "@/lib/hooks/useDataQualityFlags";

/** A small amber note at the top of the Financials tab for a ticker with open data-quality flags (docs/specs/data-quality.md): up to three plain
 * lines, gone when there are none and for flags marked reviewed in Settings. The plain amber `text-xs text-warn` line of `FmpRatiosNote`:
 * no box, no pill, no verdict wording. It annotates only; nothing on the page changes. */
export function DataQualityFlagsNote({ ticker }: { ticker: string }) {
  const { data } = useTickerDataQuality(ticker);
  const lines = noteLines(data);
  if (lines.length === 0) return null;
  return (
    <div className="space-y-0.5" data-testid="data-quality-note">
      {lines.map((line) => (
        <p key={line.key} className="text-xs text-warn">
          <Info size={13} weight="bold" aria-hidden="true" className="-mt-0.5 mr-1.5 inline" />
          {line.text}
        </p>
      ))}
    </div>
  );
}
