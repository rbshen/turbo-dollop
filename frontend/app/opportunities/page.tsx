"use client";

import { useId, useState } from "react";

import { MarketContextStrip } from "@/components/opportunities/MarketContextStrip";
import { OpportunitiesTable } from "@/components/opportunities/OpportunitiesTable";
import { PageContainer } from "@/components/layout/PageContainer";
import { AddToWatchlistButton } from "@/components/ticker/AddToWatchlistButton";
import { PageHeader } from "@/components/ui/page-header";
import { Section } from "@/components/ui/section";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/Select";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { ExportMenu } from "@/components/watchlist/ExportMenu";
import type { OpportunityListName } from "@/lib/api/types";
import { useOpportunityDates, useOpportunityRun } from "@/lib/hooks/useOpportunities";
import {
  exportFileName,
  exportRows,
  filterByTier,
  LIST_LABEL,
  rowsFor,
  thinkorswimText,
  tierCounts,
  tierFilterOptions,
  type TierFilter,
} from "@/lib/opportunities";
import { buildTradingViewText } from "@/lib/watchlistExport";

const SKELETON_ROWS = 8;

function download(content: string, type: string, fileName: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}

export default function OpportunitiesPage() {
  const dateId = useId();
  // null = the latest run; a date string = that stored run.
  const [asOf, setAsOf] = useState<string | null>(null);
  const [list, setList] = useState<OpportunityListName>("momentum");
  const [tier, setTier] = useState<TierFilter>("all");
  const { data: dates } = useOpportunityDates();
  const { data: run, error } = useOpportunityRun(asOf);

  const noRuns = dates !== undefined && dates.length === 0;
  const listRows = run ? rowsFor(run, list) : [];
  const visible = filterByTier(listRows, tier);
  const segmentCounts = tierCounts(listRows);
  const tabCount = (name: OpportunityListName) => (run ? filterByTier(rowsFor(run, name), tier).length : undefined);

  function exportTradingView() {
    if (!run) return;
    download(buildTradingViewText(exportRows(visible)).content, "text/plain", exportFileName(list, run.as_of_date, "txt"));
  }

  function exportThinkorswim() {
    if (!run) return;
    download(thinkorswimText(visible), "text/csv", exportFileName(list, run.as_of_date, "csv"));
  }

  const summary = run?.summary;
  const ranked = summary?.ranked_universe;

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader
        title="Opportunities"
        subtitle={run ? `Frozen weekly lists as of ${run.as_of_date}, built from stored data only` : "Frozen weekly lists, built from stored data only"}
        actions={
          <>
            {dates && dates.length > 0 && (
              <div className="flex items-center gap-2">
                <label htmlFor={dateId} className="text-xs text-text-secondary">
                  Snapshot date
                </label>
                <Select
                  id={dateId}
                  size="medium"
                  value={asOf ?? dates[0].as_of_date}
                  onChange={(e) => setAsOf(e.target.value === dates[0].as_of_date ? null : e.target.value)}
                >
                  {dates.map((d) => (
                    <option key={d.as_of_date} value={d.as_of_date}>
                      {d.as_of_date}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <ExportMenu
              disabled={!run}
              singleDisabled={visible.length === 0}
              onExportTradingView={exportTradingView}
              onExportThinkorswim={exportThinkorswim}
            />
            <AddToWatchlistButton
              tickers={visible.map((r) => r.ticker)}
              label="Add to watchlist"
              confirmDescription={`all ${visible.length} listed tickers`}
              disabled={visible.length === 0}
              audience={tier === "etf" ? "etf" : "stock"}
              opportunityRunId={run?.id}
            />
          </>
        }
      />

      {noRuns && <p className="text-sm text-text-tertiary">No snapshot yet — the weekly opportunity job has not run.</p>}
      {!noRuns && error && <p className="text-sm text-negative">Couldn&apos;t load the opportunity lists — {error.message}</p>}

      {!noRuns && !error && run && <MarketContextStrip market={summary?.market} asOf={run.as_of_date} />}

      {!noRuns && !error && (
        <Section>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <Tabs
              aria-label="Opportunity list"
              value={list}
              onValueChange={(v) => setList(v as OpportunityListName)}
              items={(["momentum", "reversal"] as const).map((name) => ({ value: name, label: LIST_LABEL[name], count: tabCount(name) }))}
              className="min-w-[220px]"
            />
            <SegmentedControl
              aria-label="Tier"
              value={tier}
              onValueChange={(v) => setTier(v as TierFilter)}
              options={tierFilterOptions(list).map((o) => ({
                value: o.value,
                label: (
                  <>
                    {o.label}
                    {run && <span className="ml-1.5 font-mono text-xs text-text-tertiary">{segmentCounts[o.value]}</span>}
                  </>
                ),
              }))}
            />
          </div>

          {!run && (
            <Table>
              <TableBody>
                {Array.from({ length: SKELETON_ROWS }, (_, i) => (
                  <TableRow key={i} className="animate-pulse bg-surface-2">
                    <TableCell colSpan={8} />
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {run && <OpportunitiesTable rows={visible} list={list} ruleLabels={run.rule_labels} />}
        </Section>
      )}

      {run && (
        <div className="space-y-1 text-xs text-text-tertiary">
          <p>
            Rules v{run.rules_version} ({run.rules_hash.slice(0, 8)}) · score formula v{run.score_formula_version}
            {run.weights_version != null && ` · weights v${run.weights_version}`} · {run.universe_size} tickers considered
            {summary?.gate_passed != null && `, ${summary.gate_passed} through the gate (last bar on the as-of date, 12 months of bars, $25M average daily dollar volume)`}.
          </p>
          {ranked && (
            <p>
              Momentum rank is within the tickers that pass the gate: {ranked.stocks} stocks, {ranked.etfs} ETFs and {ranked.leveraged_etfs} leveraged ETFs,
              each group ranked on its own. SPY is excluded.
            </p>
          )}
          {summary?.quality_not_covered != null && summary.quality_total != null && (
            <p>
              {summary.quality_not_covered} of {summary.quality_total} Quality tickers are not on a monitored watchlist, so the entry-signal rule
              (B3) could not apply to them.
            </p>
          )}
          {(summary?.stale_score_rows ?? 0) > 0 && (
            <p>{summary?.stale_score_rows} stored scores were on an older formula or weight set when this run was frozen.</p>
          )}
          <p>Informational only — a frozen screen of stored data, not investment advice.</p>
        </div>
      )}
    </PageContainer>
  );
}
