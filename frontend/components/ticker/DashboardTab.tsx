"use client";

import { LazyMount } from "@/components/dashboard/LazyMount";
import { PriceSection } from "@/components/dashboard/PriceSection";
import { RowSkeleton } from "@/components/dashboard/Skeleton";
import { SectionHeading } from "@/components/dashboard/SectionHeading";
import { StepsSection } from "@/components/dashboard/StepsSection";
import { VerdictStrip } from "@/components/dashboard/VerdictStrip";
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
      <VerdictStrip ticker={ticker} />
      <StepsSection data={data} error={error} loading={isLoading} />
      <PriceSection ticker={ticker} data={data} error={error} loading={isLoading} />
      {/* Section D mounts (and fetches /stuck-check) when scrolled into view; it is the next commit. */}
      <LazyMount placeholder={<RowSkeleton rows={3} />}>
        <Section className="mt-8 border-border-card" title={<SectionHeading title="Why might it be stuck?" tag="Context, not scored" />} />
      </LazyMount>
    </div>
  );
}
