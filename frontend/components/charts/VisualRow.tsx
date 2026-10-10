import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface Props {
  label: ReactNode;
  /** The score/verdict pill (a scored step) or nothing (a context-not-scored row). */
  pill?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** Label and pill on the left, the visual on the right. Below 36rem of its OWN width (the `sm` breakpoint of a full-width card) the pill and
 * label stack above the visual. A container query, so it follows the card, not the window. */
export function VisualRow({ label, pill, children, className }: Props) {
  return (
    <div className={cn("@container", className)}>
      <div className="flex flex-col gap-2 @xl:flex-row @xl:items-center @xl:gap-6">
        <div className="flex flex-wrap items-center gap-2 @xl:w-56 @xl:shrink-0">
          <span className="text-sm text-text-primary">{label}</span>
          {pill}
        </div>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
