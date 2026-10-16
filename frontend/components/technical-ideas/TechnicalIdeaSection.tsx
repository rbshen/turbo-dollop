"use client";

import { useId, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Section } from "@/components/ui/section";

interface Props {
  title: string;
  // A short chip beside the title, e.g. the candle timeframe ("2h").
  tag?: string;
  // The "as of" stamp text (already formatted, e.g. "Oct 15, 15:30 ET"); omitted until the data has loaded.
  asOf?: string | null;
  footnote?: ReactNode;
  children: ReactNode;
}

// The shell of one strategy on the Technical Ideas page: heading, timeframe tag, as-of stamp, body, footnote. A second strategy is
// another section component that renders this around its own table and data hook; the page just lists them.
export function TechnicalIdeaSection({ title, tag, asOf, footnote, children }: Props) {
  const headingId = useId();
  return (
    <Section role="region" aria-labelledby={headingId}>
      <div className="mb-3">
        <div className="flex items-center gap-2">
          <h2 id={headingId} className="text-sm font-semibold text-text-primary">
            {title}
          </h2>
          {tag && (
            <Badge size="compact" tone="neutral">
              {tag}
            </Badge>
          )}
        </div>
        {asOf && <p className="mt-1 text-xs text-text-secondary">As of {asOf}</p>}
      </div>
      {children}
      {footnote && <div className="mt-3 space-y-1 text-xs text-text-tertiary">{footnote}</div>}
    </Section>
  );
}
