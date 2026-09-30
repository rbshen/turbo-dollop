"use client";

import type { ReactNode } from "react";

import { CaretDown } from "@phosphor-icons/react";

import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

interface Props {
  title: string;
  /** How many of this section's filters are applied. A neutral count badge
   * shows in the header (so it is still visible while the section is collapsed);
   * none at zero. */
  count?: number;
  children: ReactNode;
}

// Shared collapsible card shell for the Screener sidebar's Watchlist/
// Fundamental/Technical sections -- same Collapsible primitive + trigger/
// chevron convention AnalysisSectionCard.tsx already established for the
// Analysis tab's "Show reasoning" toggle, just without that card's score/
// verdict header (these sections have no per-ticker score of their own).
// Defaults open -- unlike "Show reasoning" (deliberately hidden until
// asked for), the filters themselves are the primary content of this
// sidebar and should be visible on first load.
//
// The heading itself uses Section's title convention (text-sm font-
// semibold text-text-primary, no uppercase/tracking) rather than a bespoke
// style -- Section has no collapse behavior of its own, so this keeps the
// Collapsible mechanics and box (a sidebar needs a clear boundary between
// three stacked collapsible groups) while adopting the shared title look.
export function CollapsibleFilterSection({ title, count = 0, children }: Props) {
  return (
    <div className="rounded-lg border border-border-card bg-surface p-4">
      <Collapsible defaultOpen>
        <CollapsibleTrigger className="group flex w-full items-center justify-between gap-2 text-left">
          <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
          <span className="flex items-center gap-2">
            {count > 0 && (
              <Badge tone="neutral" size="compact" title={`${count} applied`}>
                {count}
                <span className="sr-only"> applied</span>
              </Badge>
            )}
            <CaretDown
              size={12}
              className="shrink-0 text-text-tertiary transition-transform duration-200 group-data-[panel-open]:rotate-180"
            />
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="pt-4">{children}</div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
