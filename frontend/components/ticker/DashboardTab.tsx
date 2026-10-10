"use client";

import { RowSkeleton } from "@/components/dashboard/Skeleton";
import { SectionHeading } from "@/components/dashboard/SectionHeading";
import { Section } from "@/components/ui/section";
import { useDashboard } from "@/lib/hooks/useDashboard";
import { useUniverseStatus } from "@/lib/hooks/useUniverse";

interface Props {
  ticker: string;
}

/** The Dashboard tab (docs/specs/dashboard.md): the verdicts, the five scored steps with a small visual each, price and valuation, and
 * the informational "Why might it be stuck?" section, so the owner does not switch tabs. Presentation only. */
export function DashboardTab({ ticker }: Props) {
  const { data, error, isLoading } = useDashboard(ticker);
  const { data: universe } = useUniverseStatus(ticker);

  return (
    <div className="space-y-2 py-6">
      {universe?.delisted && (
        <p className="text-sm text-text-secondary" data-testid="dashboard-delisted">
          This ticker is delisted: the figures below are the last ones cached and no longer refresh.
        </p>
      )}
      <Section title={<SectionHeading title="Verdicts" tag="As in the header" />} />
      <Section title={<SectionHeading title="Five steps" tag="Scored" />}>
        {error ? (
          <p className="text-sm text-negative">Couldn&apos;t load the steps — {error.message}</p>
        ) : isLoading || !data ? (
          <RowSkeleton rows={5} />
        ) : null}
      </Section>
      <Section title={<SectionHeading title="Price and valuation" tag="Not part of the score" />} />
      <Section className="mt-8 border-border-card" title={<SectionHeading title="Why might it be stuck?" tag="Context, not scored" />} />
    </div>
  );
}
