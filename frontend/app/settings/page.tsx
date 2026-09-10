"use client";

import { useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { DiscountRateSettingsForm } from "@/components/settings/DiscountRateSettingsForm";
import { LiquidityZoneSettingsForm } from "@/components/settings/LiquidityZoneSettingsForm";
import { MoatSettingsForm } from "@/components/settings/MoatSettingsForm";
import { ReitDividendYieldSettingsForm } from "@/components/settings/ReitDividendYieldSettingsForm";
import { WatchlistSettingsForm } from "@/components/settings/WatchlistSettingsForm";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { key: "watchlists", label: "Watchlists", Component: WatchlistSettingsForm },
  { key: "discount-rate", label: "Discount Rate", Component: DiscountRateSettingsForm },
  { key: "economic-moat", label: "Economic Moat", Component: MoatSettingsForm },
  { key: "reit", label: "REIT", Component: ReitDividendYieldSettingsForm },
  { key: "liquidity", label: "Liquidity", Component: LiquidityZoneSettingsForm },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

export default function SettingsPage() {
  const [active, setActive] = useState<SectionKey>(SECTIONS[0].key);

  // Only the active section is mounted -- each form fetches its own config via
  // SWR on mount, so rendering all 5 at once (the old vertical-stack layout)
  // fired 5 concurrent requests every page load for 4 sections the user isn't
  // even looking at yet.
  const ActiveSection = SECTIONS.find((section) => section.key === active) ?? SECTIONS[0];

  return (
    <PageContainer className="space-y-6 pb-12">
      <h1 className="font-heading pt-6 text-2xl font-semibold tracking-tight text-zinc-100">Settings</h1>
      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="w-full shrink-0 lg:w-56">
          <nav className="space-y-1 rounded-lg border border-zinc-800 bg-zinc-900/40 p-2">
            {SECTIONS.map((section) => (
              <button
                key={section.key}
                type="button"
                onClick={() => setActive(section.key)}
                className={cn(
                  "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
                  section.key === active
                    ? "bg-zinc-800 font-medium text-zinc-100"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200",
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
