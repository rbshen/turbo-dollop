"use client";

import { useState } from "react";

import { PageContainer } from "@/components/layout/PageContainer";
import { MomentumTable } from "@/components/momentum/MomentumTable";
import { PageHeader } from "@/components/ui/page-header";
import { Section } from "@/components/ui/section";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import type { MomentumPeriod } from "@/lib/api/types";
import { useMomentum } from "@/lib/hooks/useMomentum";

const PERIOD_OPTIONS: { value: MomentumPeriod; label: string }[] = [
  { value: "current", label: "This month" },
  { value: "previous", label: "Previous month" },
];

const TOP_N = 10;

// MomentumTable's own column count (Rank, Ticker, Moat, 1w, 1mo, 3mo, 6mo,
// 12mo, Composite, Score) -- used only to size this page-level loading
// skeleton's colSpan, since the skeleton renders before MomentumTable
// itself (and its real header) ever mounts.
const TABLE_COLUMN_COUNT = 10;

export default function MomentumPage() {
  const [period, setPeriod] = useState<MomentumPeriod>("current");
  const { data, error } = useMomentum(period);

  return (
    <>
      <PageContainer className="space-y-6 pb-12">
        <PageHeader
          title="Momentum"
          subtitle={
            data?.as_of_date && (
              <>
                As of {new Date(data.as_of_date).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}
                {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
              </>
            )
          }
          actions={<SegmentedControl value={period} onValueChange={(v) => setPeriod(v as MomentumPeriod)} options={PERIOD_OPTIONS} />}
        />

        {error && <p className="text-sm text-negative">Failed to load Momentum data.</p>}

        {!error && !data && (
          <Table>
            <TableBody>
              {Array.from({ length: TOP_N }, (_, i) => (
                <TableRow key={i} className="animate-pulse bg-surface-2">
                  <TableCell colSpan={TABLE_COLUMN_COUNT} />
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {!error && data && data.as_of_date === null && (
          <p className="text-sm text-text-tertiary">
            {period === "current"
              ? "No snapshot yet — the monthly job hasn't run."
              : "No previous month's snapshot available yet."}
          </p>
        )}

        {!error && data && data.as_of_date !== null && <MomentumTable rows={data.rows.slice(0, TOP_N)} />}

        <Section>
          <div className="space-y-1 text-xs text-text-tertiary">
            <p>
              Point-in-time caveat: today&apos;s Moat classification is used as the current filter — no claim is made about what each
              ticker&apos;s Moat rating would have been historically.
            </p>
            <p>Ad hoc external research using Fathom&apos;s cached data as one input — not a Fathom product feature, not investment advice.</p>
          </div>
        </Section>
      </PageContainer>
    </>
  );
}
