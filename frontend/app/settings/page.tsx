"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { DiscountRateSettingsForm } from "@/components/settings/DiscountRateSettingsForm";
import { FmpDataGroupsSection } from "@/components/settings/FmpDataGroupsSection";
import { LiquidityZoneSettingsForm } from "@/components/settings/LiquidityZoneSettingsForm";
import { MoatSettingsForm } from "@/components/settings/MoatSettingsForm";
import { ReitDividendYieldSettingsForm } from "@/components/settings/ReitDividendYieldSettingsForm";
import { ScoreWeightingForm } from "@/components/settings/ScoreWeightingForm";
import { StatusSection } from "@/components/settings/StatusSection";
import { WeinsteinSettingsForm } from "@/components/settings/WeinsteinSettingsForm";
import { PageHeader } from "@/components/ui/page-header";
import { cn } from "@/lib/utils";

// "Status" was renamed "Scheduled Jobs" and split 2026-09-27: the per-group
// FMP toggle table moved out into its own "FMP Data Groups" section, right
// after it -- StatusSection keeps just the cron jobs table (the FMP
// health-summary card moved into FMP data groups, 2026-09-30).
const SECTIONS = [
  { key: "scheduled-jobs", label: "Scheduled jobs", Component: StatusSection },
  { key: "fmp-data-groups", label: "FMP data groups", Component: FmpDataGroupsSection },
  { key: "discount-rate", label: "Discount rate by country", Component: DiscountRateSettingsForm },
  { key: "score-weighting", label: "Score weighting", Component: ScoreWeightingForm },
  { key: "economic-moat", label: "Economic moat", Component: MoatSettingsForm },
  { key: "reit", label: "REIT", Component: ReitDividendYieldSettingsForm },
  { key: "liquidity", label: "Liquidity", Component: LiquidityZoneSettingsForm },
  { key: "weinstein", label: "Weinstein", Component: WeinsteinSettingsForm },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

export default function SettingsPage() {
  // useSearchParams (for a link such as /settings?section=score-weighting) needs a Suspense boundary on a prerendered page.
  return (
    <Suspense fallback={null}>
      <SettingsContent />
    </Suspense>
  );
}

function SettingsContent() {
  // A link such as /settings?section=score-weighting opens that section; anything else opens the first.
  const requested = useSearchParams()?.get("section");
  const [active, setActive] = useState<SectionKey>(
    () => SECTIONS.find((section) => section.key === requested)?.key ?? SECTIONS[0].key,
  );

  // Only the active section is mounted -- each form fetches its own config via
  // SWR on mount, so rendering all 8 at once (the old vertical-stack layout)
  // fired concurrent requests every page load for sections the user isn't
  // even looking at yet.
  const ActiveSection = SECTIONS.find((section) => section.key === active) ?? SECTIONS[0];

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader title="Settings" />

      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="w-full shrink-0 lg:w-56">
          <nav className="space-y-1 rounded-lg border border-border-card bg-surface p-2">
            {SECTIONS.map((section) => (
              <button
                key={section.key}
                type="button"
                onClick={() => setActive(section.key)}
                className={cn(
                  "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                  section.key === active
                    ? "bg-surface-2 font-medium text-text-primary"
                    : "text-text-secondary hover:bg-surface-2/60 hover:text-text-primary",
                )}
              >
                {section.label}
              </button>
            ))}
          </nav>
        </aside>

        <div className="min-w-0 flex-1">
          <ActiveSection.Component />
        </div>
      </div>
    </PageContainer>
  );
}
