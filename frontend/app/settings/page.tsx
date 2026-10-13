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
import { useAuth } from "@/lib/auth/AuthProvider";
import { cn } from "@/lib/utils";

// "Status" was renamed "Scheduled Jobs" and split 2026-09-27: the per-group
// FMP toggle table moved out into its own "FMP Data Groups" section, right
// after it -- StatusSection keeps just the cron jobs table (the FMP
// health-summary card moved into FMP data groups, 2026-09-30).
// `adminOnly` sections read endpoints that answer 403 to a viewer (cron-health, data-groups, data-source-health): a viewer is not
// shown them and they are never mounted, so nothing is fetched for them. The other six are readable by a viewer, who sees their
// values read-only (SettingsSection / SettingsFooter).
const SECTIONS = [
  { key: "scheduled-jobs", label: "Scheduled jobs", Component: StatusSection, adminOnly: true },
  { key: "fmp-data-groups", label: "FMP data groups", Component: FmpDataGroupsSection, adminOnly: true },
  { key: "discount-rate", label: "Discount rate by country", Component: DiscountRateSettingsForm, adminOnly: false },
  { key: "score-weighting", label: "Score weighting", Component: ScoreWeightingForm, adminOnly: false },
  { key: "economic-moat", label: "Economic moat", Component: MoatSettingsForm, adminOnly: false },
  { key: "reit", label: "REIT", Component: ReitDividendYieldSettingsForm, adminOnly: false },
  { key: "liquidity", label: "Liquidity", Component: LiquidityZoneSettingsForm, adminOnly: false },
  { key: "weinstein", label: "Weinstein", Component: WeinsteinSettingsForm, adminOnly: false },
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
  const { isAdmin, isLoading } = useAuth();
  // Until the role is known nothing is mounted: the first section is an admin one, and a viewer's page must not fetch it even once.
  if (isLoading) return <PageContainer className="space-y-6 pb-12"><PageHeader title="Settings" /></PageContainer>;
  return <SettingsSections isAdmin={isAdmin} />;
}

function SettingsSections({ isAdmin }: { isAdmin: boolean }) {
  const sections = SECTIONS.filter((section) => isAdmin || !section.adminOnly);
  // A link such as /settings?section=score-weighting opens that section; anything else (or a section the viewer cannot see) opens the first.
  const requested = useSearchParams()?.get("section");
  const [active, setActive] = useState<SectionKey>(() => sections.find((section) => section.key === requested)?.key ?? sections[0].key);

  // Only the active section is mounted -- each form fetches its own config via
  // SWR on mount, so rendering all 8 at once (the old vertical-stack layout)
  // fired concurrent requests every page load for sections the user isn't
  // even looking at yet.
  const ActiveSection = sections.find((section) => section.key === active) ?? sections[0];

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader title="Settings" />

      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="w-full shrink-0 lg:w-56">
          <nav className="space-y-1 rounded-lg border border-border-card bg-surface p-2">
            {sections.map((section) => (
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
