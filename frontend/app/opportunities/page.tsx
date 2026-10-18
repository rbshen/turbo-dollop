"use client";

import { useEffect, useId, useRef, useState } from "react";

import { MarketContextStrip } from "@/components/opportunities/MarketContextStrip";
import { OpportunitiesTable } from "@/components/opportunities/OpportunitiesTable";
import { PageContainer } from "@/components/layout/PageContainer";
import { AdminOnly } from "@/components/auth/AdminOnly";
import { AddToWatchlistButton, type AddedResult } from "@/components/ticker/AddToWatchlistButton";
import { Button } from "@/components/ui/button";
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
  toggleAllShown,
  toggleSelection,
  type ExportScope,
  type TierFilter,
} from "@/lib/opportunities";
import { buildTradingViewText } from "@/lib/watchlistExport";

const SKELETON_ROWS = 8;
const NOTICE_MS = 5000;

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

  // Selection is held by ticker: it survives the tier filter and the Momentum / Reversal tabs, and is cleared when the snapshot date
  // changes and after a successful Add to watchlist. A ticker is on one list per run, so a ticker names one row.
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const anchor = useRef<string | null>(null);
  // One quiet, transient line beside the selection count ("Select at least one ticker", "Added 12 to Growth", "Nothing to export").
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    if (notice === null) return;
    const t = setTimeout(() => setNotice(null), NOTICE_MS);
    return () => clearTimeout(t);
  }, [notice]);

  const noRuns = dates !== undefined && dates.length === 0;
  const listRows = run ? rowsFor(run, list) : [];
  const visible = filterByTier(listRows, tier);
  const segmentCounts = tierCounts(listRows);
  const tabCount = (name: OpportunityListName) => (run ? filterByTier(rowsFor(run, name), tier).length : undefined);

  // Every row of the shown run that is selected (either tab, any tier), in the run's own order.
  const selectedRows = run ? [...run.momentum, ...run.reversal].filter((r) => selected.has(r.ticker)) : [];
  const selectedTickers = selectedRows.map((r) => r.ticker);
  const hasSelection = selectedRows.length > 0;
  // A stock cannot join the ETF-only list, so the menu offers it only when every selected row is an ETF.
  const addAudience = hasSelection && selectedRows.every((r) => r.tier === "etf") ? "etf" : "stock";

  function changeSnapshot(value: string) {
    setAsOf(value === dates?.[0].as_of_date ? null : value);
    setSelected(new Set());
    setNotice(null);
    anchor.current = null;
  }

  function toggleRow(ticker: string, shiftKey: boolean) {
    const from = anchor.current; // read now: the updater below runs later, after the anchor has moved on
    const shown = visible.map((r) => r.ticker);
    setSelected((prev) => toggleSelection(prev, shown, ticker, from, shiftKey));
    anchor.current = ticker;
    setNotice(null);
  }

  function toggleAll() {
    setSelected((prev) => toggleAllShown(prev, visible.map((r) => r.ticker)));
    anchor.current = null;
    setNotice(null);
  }

  function clearSelection() {
    setSelected(new Set());
    anchor.current = null;
  }

  function added(r: AddedResult) {
    clearSelection();
    const what = r.tickers.length === 1 ? r.tickers[0] : `${r.added}`;
    setNotice(`Added ${what} to “${r.watchlistName}”${r.alreadyPresent > 0 ? ` (${r.alreadyPresent} already there)` : ""}`);
  }

  // Export: the selected rows if any, otherwise everything in the current view (tab plus tier filter); never the whole weekly run.
  const exportScope: ExportScope = hasSelection ? "selection" : "view";
  const exportSet = hasSelection ? selectedRows : visible;
  const exportLabel = hasSelection ? `Export ${selectedRows.length} selected` : `Export ${visible.length} shown`;
  const exportLists: OpportunityListName[] = hasSelection
    ? (["momentum", "reversal"] as const).filter((name) => selectedRows.some((r) => r.list_name === name))
    : [list];

  function exportTradingView() {
    if (!run) return;
    if (exportSet.length === 0) return setNotice("Nothing to export");
    download(buildTradingViewText(exportRows(exportSet)).content, "text/plain", exportFileName(exportLists, exportScope, run.as_of_date, "txt"));
  }

  function exportThinkorswim() {
    if (!run) return;
    if (exportSet.length === 0) return setNotice("Nothing to export");
    download(thinkorswimText(exportSet), "text/csv", exportFileName(exportLists, exportScope, run.as_of_date, "csv"));
  }

  const summary = run?.summary;
  const ranked = summary?.ranked_universe;

  return (
    <PageContainer className="space-y-6 pb-12">
      <PageHeader
        title="Weekly Routine"
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
                  onChange={(e) => changeSnapshot(e.target.value)}
                >
                  {dates.map((d) => (
                    <option key={d.as_of_date} value={d.as_of_date}>
                      {d.as_of_date}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <ExportMenu label={exportLabel} onExportTradingView={exportTradingView} onExportThinkorswim={exportThinkorswim} />
            <AdminOnly>
              <AddToWatchlistButton
                // a new selection is a new add: fresh "Added" / confirm state
                key={selectedTickers.join(",")}
                tickers={selectedTickers}
                label={hasSelection ? `Add ${selectedRows.length} to watchlist` : "Add to watchlist"}
                confirmDescription={`${selectedRows.length} selected tickers`}
                audience={addAudience}
                opportunityRunId={run?.id}
                onEmptyClick={() => setNotice("Select at least one ticker")}
                onAdded={added}
              />
            </AdminOnly>
          </>
        }
      />

      {noRuns && <p className="text-sm text-text-tertiary">No snapshot yet — the weekly routine job has not run.</p>}
      {!noRuns && error && <p className="text-sm text-negative">Couldn&apos;t load the weekly routine lists — {error.message}</p>}

      {!noRuns && !error && run && <MarketContextStrip market={summary?.market} asOf={run.as_of_date} />}

      {!noRuns && !error && (
        <Section>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <Tabs
              aria-label="Weekly Routine list"
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

          {/* Always rendered at a fixed height, so the line appearing never moves the table. */}
          <div className="mb-2 flex h-8 items-center gap-3 text-xs text-text-secondary" role="status" aria-live="polite">
            {notice !== null ? (
              <span>{notice}</span>
            ) : hasSelection ? (
              <>
                <span>{selectedRows.length} selected</span>
                <Button variant="ghost" size="sm" onClick={clearSelection}>
                  Clear
                </Button>
              </>
            ) : null}
          </div>

          {!run && (
            <Table>
              <TableBody>
                {Array.from({ length: SKELETON_ROWS }, (_, i) => (
                  <TableRow key={i} className="animate-pulse bg-surface-2">
                    <TableCell colSpan={9} />
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {run && (
            <OpportunitiesTable
              rows={visible}
              list={list}
              ruleLabels={run.rule_labels}
              selected={selected}
              onToggle={toggleRow}
              onToggleAll={toggleAll}
            />
          )}
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
