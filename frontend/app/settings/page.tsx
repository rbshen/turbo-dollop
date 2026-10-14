"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

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
import { Tabs, TabsPanel } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth/AuthProvider";

// "Status" was renamed "Scheduled Jobs" and split 2026-09-27: the per-group
// FMP toggle table moved out into its own "FMP Data Groups" section, right
// after it -- StatusSection keeps just the cron jobs table (the FMP
// health-summary card moved into FMP data groups, 2026-09-30).
// The whole page is admin only (2026-10-14): a viewer is sent home and none of this is mounted, so nothing is fetched for them. The
// backend refuses a viewer's calls to every Settings-only endpoint too (core/route_roles.py); the redirect is UX only.
// Shown as tabs, in this order.
const SECTIONS = [
  { key: "fmp-data-groups", label: "FMP data groups", Component: FmpDataGroupsSection },
  { key: "scheduled-jobs", label: "Scheduled jobs", Component: StatusSection },
  { key: "score-weighting", label: "Score weighting", Component: ScoreWeightingForm },
  { key: "economic-moat", label: "Economic moat", Component: MoatSettingsForm },
  { key: "discount-rate", label: "Discount rate by country", Component: DiscountRateSettingsForm },
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
  const { isAdmin, isLoading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!isLoading && !isAdmin) router.replace("/");
  }, [isLoading, isAdmin, router]);

  // Until the role is known, and for anyone who is not an admin, nothing is mounted: no section, so no request.
  if (isLoading || !isAdmin) return null;
  return <SettingsSections />;
}

function SettingsSections() {
  const router = useRouter();
  // The active tab lives in the URL as ?section=<key>, so a refresh or a shared link lands on it (the Overall card links to
  // /settings?section=score-weighting). A missing or unknown value opens the first tab.
  const requested = useSearchParams()?.get("section");
  const [active, setActive] = useState<SectionKey>(() => SECTIONS.find((section) => section.key === requested)?.key ?? SECTIONS[0].key);

  const select = (key: string) => {
    setActive(key as SectionKey);
    router.replace(`/settings?section=${key}`, { scroll: false });
  };

  // Only the active section is mounted -- each form fetches its own config via SWR on mount, so rendering all of them at once would
  // fire concurrent requests on every page load for sections the user isn't looking at.
  const ActiveSection = SECTIONS.find((section) => section.key === active) ?? SECTIONS[0];

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader title="Settings" />

      <Tabs
        value={active}
        onValueChange={select}
        aria-label="Settings sections"
        items={SECTIONS.map(({ key, label }) => ({ value: key, label }))}
      >
        <TabsPanel value={ActiveSection.key} className="min-w-0 pt-6">
          <ActiveSection.Component />
        </TabsPanel>
      </Tabs>
    </PageContainer>
  );
}
