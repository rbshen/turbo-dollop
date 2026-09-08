"use client";

import { useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { MomentumBanner } from "@/components/momentum/MomentumBanner";
import { MomentumTable } from "@/components/momentum/MomentumTable";
import { SegmentedControl } from "@/components/shared/SegmentedControl";
import type { MomentumPeriod } from "@/lib/api/types";
import { useMomentum } from "@/lib/hooks/useMomentum";

const PERIOD_OPTIONS: { value: MomentumPeriod; label: string }[] = [
  { value: "current", label: "This month" },
  { value: "previous", label: "Previous month" },
];

const TOP_N = 10;

export default function MomentumPage() {
  const [period, setPeriod] = useState<MomentumPeriod>("current");
  const { data, error } = useMomentum(period);

  return (
    <>
      <MomentumBanner />
      <PageContainer className="space-y-6 pb-12 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-heading text-xl font-semibold text-text-primary">Momentum</h1>
            {data?.as_of_date && (
              <p className="text-xs text-text-tertiary">
                As of {new Date(data.as_of_date).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}
                {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
              </p>
            )}
          </div>
          <SegmentedControl value={period} onChange={setPeriod} options={PERIOD_OPTIONS} />
        </div>

        {error && <p className="text-sm text-negative">Failed to load Momentum data.</p>}

        {!error && !data && <p className="text-sm text-text-tertiary animate-pulse">Loading Momentum…</p>}

        {!error && data && data.as_of_date === null && (
          <p className="text-sm text-text-tertiary">
            {period === "current"
              ? "No snapshot yet — the monthly job hasn't run."
              : "No previous month's snapshot available yet."}
          </p>
        )}

        {!error && data && data.as_of_date !== null && <MomentumTable rows={data.rows.slice(0, TOP_N)} />}

        <div className="space-y-1 border-t border-border-subtle pt-4 text-xs text-text-tertiary">
          <p>
            Point-in-time caveat: today&apos;s Moat classification is used as the current filter — no claim is made about what each
            ticker&apos;s Moat rating would have been historically.
          </p>
          <p>Ad hoc external research using Fathom&apos;s cached data as one input — not a Fathom product feature, not investment advice.</p>
        </div>
      </PageContainer>
    </>
  );
}
