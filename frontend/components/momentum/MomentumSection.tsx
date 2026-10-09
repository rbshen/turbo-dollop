"use client";

import { useId, useState, type ReactNode } from "react";

import { MomentumTable, type MomentumTableRow } from "@/components/momentum/MomentumTable";
import { Section } from "@/components/ui/section";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import type { MomentumPeriod } from "@/lib/api/types";
import { fmtEventDate } from "@/lib/chartEventMarkers";

const PERIOD_OPTIONS: { value: MomentumPeriod; label: string }[] = [
  { value: "current", label: "This month" },
  { value: "previous", label: "Previous month" },
];

// MomentumTable's own column count -- used only to size the loading skeleton's colSpan, since the
// skeleton renders before the table (and its real header) ever mounts.
const COLUMNS_WITH_MOAT_AND_SCORE = 11;
const COLUMNS_WITHOUT_MOAT_AND_SCORE = 9;

interface SnapshotResponse {
  as_of_date: string | null;
  computed_at: string | null;
  rows: MomentumTableRow[];
}

interface Props {
  title: string;
  // Module-level data hook (useMomentum / useEtfMomentum); the section owns the period it is called with.
  useData: (period: MomentumPeriod) => { data?: SnapshotResponse; error?: Error };
  // Rows shown (the stock endpoint returns the full ranking, the ETF endpoint only its top 5).
  topN: number;
  showMoatAndScore?: boolean;
  footnote?: ReactNode;
}

// One titled Momentum table with its own This month | Previous month toggle, data, skeleton and
// empty/error text. The Stock and ETF sections each render one, fully independent of the other.
export function MomentumSection({ title, useData, topN, showMoatAndScore = true, footnote }: Props) {
  const [period, setPeriod] = useState<MomentumPeriod>("current");
  const { data, error } = useData(period);
  const headingId = useId();

  return (
    <Section role="region" aria-labelledby={headingId}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-sm font-semibold text-text-primary">
            {title}
          </h2>
          {data?.as_of_date && (
            <p className="mt-1 text-xs text-text-secondary">
              As of {fmtEventDate(data.as_of_date)}
              {data.computed_at && ` · Computed ${new Date(data.computed_at).toLocaleString()}`}
            </p>
          )}
        </div>
        <SegmentedControl
          aria-label={`${title} period`}
          value={period}
          onValueChange={(v) => setPeriod(v as MomentumPeriod)}
          options={PERIOD_OPTIONS}
        />
      </div>

      {error && <p className="text-sm text-negative">Failed to load {title} Momentum data.</p>}

      {!error && !data && (
        <Table>
          <TableBody>
            {Array.from({ length: topN }, (_, i) => (
              <TableRow key={i} className="animate-pulse bg-surface-2">
                <TableCell colSpan={showMoatAndScore ? COLUMNS_WITH_MOAT_AND_SCORE : COLUMNS_WITHOUT_MOAT_AND_SCORE} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {!error && data && data.as_of_date === null && (
        <p className="text-sm text-text-tertiary">
          {period === "current" ? "No snapshot yet — the monthly job hasn't run." : "No previous month's snapshot available yet."}
        </p>
      )}

      {!error && data && data.as_of_date !== null && <MomentumTable rows={data.rows.slice(0, topN)} showMoatAndScore={showMoatAndScore} />}

      {footnote && <div className="mt-3 space-y-1 text-xs text-text-tertiary">{footnote}</div>}
    </Section>
  );
}
