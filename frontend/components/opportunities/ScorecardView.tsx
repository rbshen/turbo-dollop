"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/ui/section";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/Select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiFetch } from "@/lib/api/client";
import type {
  FlagCellPair,
  FlagCells,
  FlagTrigger,
  ScorecardBenchmark,
  ScorecardCell,
  ScorecardCounts,
  ScorecardFlagsOut,
  ScorecardGroup,
  ScorecardOut,
  ScorecardOutcomesOut,
  ScorecardState,
} from "@/lib/api/types";
import { LIST_LABEL, tierLabel } from "@/lib/opportunities";
import { useScorecard, useScorecardFlags, useScorecardPicks, type ScorecardFilters } from "@/lib/hooks/useOpportunities";
import {
  BENCHMARK_LABEL,
  BENCHMARK_NAME,
  cellOf,
  cohortsPositive,
  csvFileName,
  earlyBanner,
  excessClass,
  exclusionLine,
  fmtFrac,
  fmtShare,
  groupLabel,
  HORIZON_OPTIONS,
  ledgerCells,
  outcomesCsv,
  scorecardCsv,
  STATE_LABEL,
  STATE_TITLE,
  TRIGGER_LABEL,
  weightsNote,
} from "@/lib/scorecard";

const HEAD = "text-xs font-medium text-text-tertiary";
const NUM = "text-right font-mono tabular-nums";
const MUTED = "text-text-tertiary";
const MAX_LEDGER_ROWS = 300;

function download(content: string, type: string, fileName: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}

/** "Too early" / "Early" pill (nothing for a cell past the gate). */
function StatePill({ state }: { state: ScorecardState }) {
  const label = STATE_LABEL[state];
  if (!label) return null;
  return (
    <Badge size="compact" tone={state === "early" ? "caution" : "neutral"} title={STATE_TITLE[state]}>
      {label}
    </Badge>
  );
}

function Dash({ title }: { title?: string }) {
  return (
    <span className={MUTED} title={title}>
      —
    </span>
  );
}

// --- the main table ---------------------------------------------------------------------------------------------------------------

function ValueCells({ cell, group }: { cell: ScorecardCell; group: ScorecardGroup }) {
  const v = cell.values;
  if (!v) {
    return (
      <>
        {Array.from({ length: 10 }, (_, i) => (
          <TableCell key={i} className={`${NUM} ${MUTED}`}>
            —
          </TableCell>
        ))}
      </>
    );
  }
  const st = cell.state;
  const pool = cell.pool;
  const sens = cell.n_censored > 0 ? v.including_censored.median_excess : null;
  return (
    <>
      <TableCell className={`${NUM} ${excessClass(v.median_excess, st)}`}>
        {fmtFrac(v.median_excess)}
        {sens != null && (
          <span className="block text-[11px] text-text-tertiary" title="Median excess if the censored rows are included, at the last bar they have">
            incl. censored {fmtFrac(sens)}
          </span>
        )}
      </TableCell>
      <TableCell className={`${NUM} ${excessClass(v.mean_excess, st)}`}>{fmtFrac(v.mean_excess)}</TableCell>
      <TableCell className={`${NUM} text-text-secondary`} title="Share of complete rows with a return above the benchmark's over the same dates">
        {fmtShare(v.share_above)}
      </TableCell>
      <TableCell className={`${NUM} text-text-secondary`} title="Cohorts (weekly lists) whose own median excess is above zero">
        {cohortsPositive(v.cohorts_positive, v.cohorts_counted)}
      </TableCell>
      <TableCell className={`${NUM} text-text-secondary`}>{fmtFrac(v.benchmark_median_return)}</TableCell>
      <TableCell
        className={`${NUM} text-text-secondary`}
        title={group.has_pool ? (pool ? `Pool names the stage sent to the same list and tier: ${pool.n_complete} complete rows, ${pool.cohorts} cohorts` : undefined) : "Rule cuts have no pool baseline"}
      >
        {pool?.values ? fmtFrac(pool.values.median_excess) : <Dash />}
      </TableCell>
      <TableCell className={`${NUM} text-text-secondary`} title="Median over cohorts of (listed median excess minus pool median excess)">
        {cell.listed_minus_pool?.median_excess != null ? fmtFrac(cell.listed_minus_pool.median_excess) : <Dash />}
      </TableCell>
      <TableCell className={`${NUM} text-text-secondary`} title={`Complete rows only (${v.stop_n}); a 10% intraday stop from the entry bar`}>
        {fmtShare(v.stop_hit_rate)}
      </TableCell>
      <TableCell className={`${NUM} text-text-secondary`} title="Stop fill if the stop was hit, else the buy-and-hold return">
        {fmtFrac(v.median_with_stop_return)}
      </TableCell>
      <TableCell className={`${NUM} text-text-secondary`} title="Median worst move and median peak-to-trough drawdown inside the window">
        {fmtFrac(v.median_worst_move, 1)} / {fmtFrac(v.median_drawdown, 1)}
      </TableCell>
    </>
  );
}

function GroupRow({ group, horizon, benchmark }: { group: ScorecardGroup; horizon: number; benchmark: ScorecardBenchmark }) {
  const cell = cellOf(group, horizon, benchmark);
  const indent = group.kind === "tier" || group.kind === "leveraged" ? "pl-6" : group.kind === "rule" ? "pl-3" : "";
  const note = weightsNote(cell);
  const lines = exclusionLine(cell);
  return (
    <TableRow data-testid={`group-${group.key}`}>
      <TableCell className={`${indent} whitespace-nowrap`}>
        <span className={group.kind === "list" ? "font-medium text-text-primary" : "text-text-secondary"}>{groupLabel(group)}</span>
        {note && (
          <Badge size="compact" className="ml-2" title={note}>
            Mixed weights
          </Badge>
        )}
      </TableCell>
      <TableCell className={NUM}>
        <span className="text-text-primary">{cell.n_complete}</span>
        {lines && <span className="block text-[11px] text-text-tertiary">{lines}</span>}
      </TableCell>
      <TableCell className={`${NUM} text-text-secondary`} title={`${cell.cohorts} of ${cell.cohorts_total} weekly lists have a complete row in this cell`}>
        {cell.cohorts}
      </TableCell>
      <TableCell>
        <StatePill state={cell.state} />
      </TableCell>
      <ValueCells cell={cell} group={group} />
    </TableRow>
  );
}

const MAIN_HEADS: { label: string; title?: string; right?: boolean }[] = [
  { label: "Group" },
  { label: "n", title: "Complete rows used. Pending, censored and entry-gap rows are counted below and left out of every figure.", right: true },
  { label: "Lists", title: "Weekly lists (cohorts) with a complete row", right: true },
  { label: "" },
  { label: "Median excess", title: "Median of the per-list medians of (return minus benchmark return)", right: true },
  { label: "Mean", title: "Mean excess over all complete rows", right: true },
  { label: "Above benchmark", right: true },
  { label: "Lists positive", right: true },
  { label: "Benchmark", title: "The benchmark's own median return over the same dates", right: true },
  { label: "Pool", title: "Median excess of the pool names the rules left out (same list and tier)", right: true },
  { label: "Listed − pool", right: true },
  { label: "Stop hit", right: true },
  { label: "With stop", title: "Median return with the 10% stop applied", right: true },
  { label: "Worst / drawdown", right: true },
];

function ScorecardTable({ data, horizon, benchmark }: { data: ScorecardOut; horizon: number; benchmark: ScorecardBenchmark }) {
  const rules = data.groups.filter((g) => g.kind === "rule");
  const rest = data.groups.filter((g) => g.kind !== "rule");
  return (
    <Table aria-label="Scorecard">
      <TableHeader>
        <TableRow className="h-9">
          {MAIN_HEADS.map((h, i) => (
            <TableHead key={i} className={`${HEAD} ${h.right ? "text-right" : ""}`} title={h.title}>
              {h.label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rest.map((g) => (
          <GroupRow key={g.key} group={g} horizon={horizon} benchmark={benchmark} />
        ))}
        <TableRow className="h-9">
          <TableCell colSpan={MAIN_HEADS.length} className="text-xs text-text-tertiary">
            Rule cuts overlap each other and the lists above, so they are shown on their own and never added together.
          </TableCell>
        </TableRow>
        {rules.map((g) => (
          <GroupRow key={g.key} group={g} horizon={horizon} benchmark={benchmark} />
        ))}
      </TableBody>
    </Table>
  );
}

// --- flags ------------------------------------------------------------------------------------------------------------------------

function FlagStats({ pair }: { pair: FlagCellPair | undefined }) {
  const f = pair?.flagged;
  const u = pair?.unflagged;
  if (!f) return <><TableCell className={`${NUM} ${MUTED}`}>—</TableCell><TableCell className={`${NUM} ${MUTED}`}>—</TableCell><TableCell className={`${NUM} ${MUTED}`}>—</TableCell></>;
  return (
    <>
      <TableCell className={NUM} title={exclusionLine(f) || undefined}>
        <span className="text-text-primary">{f.n_complete}</span>
        <span className="ml-1.5 inline-block align-middle">
          <StatePill state={f.state} />
        </span>
      </TableCell>
      <TableCell className={`${NUM} ${f.values ? excessClass(f.values.median_excess, f.state) : MUTED}`}>{f.values ? fmtFrac(f.values.median_excess) : "—"}</TableCell>
      <TableCell className={`${NUM} ${u?.values ? "text-text-secondary" : MUTED}`} title={u ? `${u.n_complete} complete rows from ${u.cohorts} lists` : undefined}>
        {u?.values ? fmtFrac(u.values.median_excess) : "—"}
      </TableCell>
    </>
  );
}

function FlagCountsTable({ flags, horizon, benchmark }: { flags: ScorecardFlagsOut; horizon: number; benchmark: ScorecardBenchmark }) {
  const h = String(horizon);
  const pair = (cells: FlagCells) => cells[h]?.[benchmark];
  const triggers = (["D1", "D2", "D3"] as FlagTrigger[]).map((t) => flags.triggers[t]);
  const head = (label: string, right = true, title?: string) => (
    <TableHead className={`${HEAD} ${right ? "text-right" : ""}`} title={title}>
      {label}
    </TableHead>
  );
  return (
    <Table aria-label="Flag counts">
      <TableHeader>
        <TableRow className="h-9">
          {head("Trigger", false)}
          {head("Eligible", true, "Names on the list the trigger can apply to")}
          {head("Flagged", true)}
          {head("Not covered", true, "D1 only: not on a monitored watchlist, so the signal jobs never looked. Not 'no flag'.")}
          {head("Incomplete", true, "Could not be judged on some night. Not 'no flag'.")}
          {head("Unflagged", true, "Eligible, minus flagged, not covered and incomplete")}
          {head("Windows open", true, "Weekly lists whose flag window is still open (the latest list)")}
          {head(`Complete @ ${horizon}`, true, "Flagged names with a complete result, priced from the flag date")}
          {head("Flagged excess", true)}
          {head("Unflagged excess", true, `${flags.comparator_label}: the same list's unflagged eligible names, priced from the list date`)}
        </TableRow>
      </TableHeader>
      <TableBody>
        {triggers.map((t) => (
          <FlagTriggerRows key={t.trigger} t={t} pair={pair} />
        ))}
        <TableRow>
          <TableCell className="text-text-secondary" title="One flag per name: the earliest. Triggers are never added together.">
            Any flag (first per name)
          </TableCell>
          <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
          <TableCell className={`${NUM} text-text-primary`}>{flags.any_flag.flagged_names}</TableCell>
          <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
          <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
          <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
          <TableCell className={`${NUM} text-text-secondary`}>{flags.any_flag.flagged_in_open_cohorts} in open</TableCell>
          <FlagStats pair={pair(flags.any_flag.cells)} />
        </TableRow>
      </TableBody>
    </Table>
  );
}

function FlagTriggerRows({ t, pair }: { t: ScorecardFlagsOut["triggers"][FlagTrigger]; pair: (c: FlagCells) => FlagCellPair | undefined }) {
  return (
    <>
      <TableRow data-testid={`trigger-${t.trigger}`}>
        <TableCell className="text-text-primary">{TRIGGER_LABEL[t.trigger]}</TableCell>
        <TableCell className={NUM}>{t.eligible}</TableCell>
        <TableCell className={`${NUM} text-text-primary`}>{t.flagged}</TableCell>
        <TableCell className={NUM}>{t.trigger === "D1" ? t.not_covered : <Dash title="Only D1 can be not covered" />}</TableCell>
        <TableCell className={NUM}>{t.incomplete}</TableCell>
        <TableCell className={NUM} title={t.comparator_provisional ? "Provisional: a name can still flag while a window is open" : undefined}>
          {t.unflagged}
          {t.comparator_provisional && <span className="text-text-tertiary"> *</span>}
        </TableCell>
        <TableCell className={`${NUM} text-text-secondary`}>
          {t.cohorts_window_open} of {t.cohorts}
        </TableCell>
        <FlagStats pair={pair(t.cells)} />
      </TableRow>
      {t.split &&
        ([
          ["Already within 5% of the MA on the list date", t.split.already_at_ma_on_list],
          ["Not yet at the MA on the list date", t.split.not_at_ma_on_list],
        ] as const).map(([label, part]) => (
          <TableRow key={label}>
            <TableCell className="pl-6 text-text-secondary">{label}</TableCell>
            <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
            <TableCell className={NUM}>{part.flagged}</TableCell>
            <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
            <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
            <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
            <TableCell className={`${NUM} ${MUTED}`}>—</TableCell>
            <FlagStats pair={pair(part.cells)} />
          </TableRow>
        ))}
    </>
  );
}

function FlagLedger({ flags, horizon, benchmark }: { flags: ScorecardFlagsOut; horizon: number; benchmark: ScorecardBenchmark }) {
  const rows = flags.ledger.slice(0, MAX_LEDGER_ROWS);
  if (rows.length === 0) return <p className="py-3 text-sm text-text-tertiary">No flags yet.</p>;
  return (
    <>
      <Table aria-label="Flag ledger">
        <TableHeader>
          <TableRow className="h-9">
            <TableHead className={HEAD}>Ticker</TableHead>
            <TableHead className={HEAD}>Trigger</TableHead>
            <TableHead className={HEAD}>List</TableHead>
            <TableHead className={HEAD}>Flag date</TableHead>
            <TableHead className={`${HEAD} text-right`}>{horizon}-session return</TableHead>
            <TableHead className={`${HEAD} text-right`}>Excess vs {BENCHMARK_LABEL[benchmark]}</TableHead>
            <TableHead className={HEAD}>Stop</TableHead>
            <TableHead className={HEAD} />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => {
            const c = ledgerCells(r, horizon, benchmark);
            return (
              <TableRow key={r.flag_id}>
                <TableCell>
                  <a href={`/tickers/${r.ticker}`} target="_blank" rel="noopener noreferrer" className="font-mono text-sm font-semibold text-text-primary">
                    {r.ticker}
                  </a>
                </TableCell>
                <TableCell className="text-text-secondary" title={r.trigger_id}>
                  {r.trigger}
                </TableCell>
                <TableCell className="text-text-secondary">
                  {LIST_LABEL[r.list_name]} · {tierLabel(r.tier, r.list_name)}
                </TableCell>
                <TableCell className="font-mono text-text-secondary">{r.flag_date}</TableCell>
                <TableCell className={`${NUM} text-text-secondary`}>{c.ret != null ? fmtFrac(c.ret) : <Dash title={c.status} />}</TableCell>
                <TableCell className={`${NUM} text-text-secondary`}>{c.excess != null ? fmtFrac(c.excess) : <Dash title={c.status} />}</TableCell>
                <TableCell className="text-text-secondary">{c.stop}</TableCell>
                <TableCell>
                  <div className="flex flex-nowrap items-center gap-1">
                    {r.window_open && (
                      <Badge size="compact" title="The list this flag belongs to is the latest one: more flags can still arrive">
                        Window open
                      </Badge>
                    )}
                    {r.leveraged && <Badge size="compact">Leveraged</Badge>}
                    {r.trigger === "D3" && r.already_at_ma_on_list && (
                      <Badge size="compact" title="Already within 5% of the moving average on the list date">
                        At MA on list
                      </Badge>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {flags.ledger.length > MAX_LEDGER_ROWS && <p className="py-2 text-xs text-text-tertiary">Showing the latest {MAX_LEDGER_ROWS} of {flags.ledger.length} flags.</p>}
    </>
  );
}

// --- picks ----------------------------------------------------------------------------------------------------------------------------

function PicksLine({ filters, horizon, benchmark }: { filters: ScorecardFilters; horizon: number; benchmark: ScorecardBenchmark }) {
  const { data } = useScorecardPicks(filters);
  if (!data) return null;
  if (data.empty) return <p className="text-sm text-text-tertiary">No picks yet. Picks are the names you add to a watchlist from the Weekly Routine page.</p>;
  const cell: (ScorecardCounts & { values: ScorecardCell["values"] }) | undefined = data.cells?.[String(horizon)]?.[benchmark];
  return (
    <div className="space-y-1 text-sm text-text-secondary">
      <p>
        {data.count} {data.count === 1 ? "pick" : "picks"} across {data.cohorts} weekly {data.cohorts === 1 ? "list" : "lists"}
        {data.unmatched > 0 && ` (${data.unmatched} without a stored list)`}. <span className="text-text-tertiary">{data.label}.</span>
      </p>
      {cell && (
        <p className="font-mono text-xs tabular-nums">
          {horizon}-session: {cell.n_complete} complete{exclusionLine(cell) ? ` · ${exclusionLine(cell)}` : ""}
          {cell.values ? ` · median excess ${fmtFrac(cell.values.median_excess)}` : ""} {cell.state === "too_early" && <StatePill state={cell.state} />}
        </p>
      )}
    </div>
  );
}

// --- the view ----------------------------------------------------------------------------------------------------------------------------

export function ScorecardView() {
  const [horizon, setHorizon] = useState<number>(5);
  const [benchmark, setBenchmark] = useState<ScorecardBenchmark>("spy");
  const [filters, setFilters] = useState<ScorecardFilters>({ rulesVersion: null, triggersVersion: null, weightsVersion: null });
  const [exportError, setExportError] = useState<string | null>(null);
  const { data, error } = useScorecard(filters);
  const { data: flags, error: flagsError } = useScorecardFlags(filters);

  async function exportOutcomes() {
    setExportError(null);
    try {
      const q = new URLSearchParams({ limit: "20000" });
      if (filters.rulesVersion) q.set("rules_version", filters.rulesVersion);
      const listed = await apiFetch<ScorecardOutcomesOut>(`/opportunities/scorecard/outcomes?${q}`);
      const flagged = await apiFetch<ScorecardOutcomesOut>(`/opportunities/scorecard/outcomes?source=flags&limit=20000`);
      const rows = [...listed.rows, ...flagged.rows];
      download(outcomesCsv(rows), "text/csv", csvFileName("outcomes", data?.latest.outcomes_spy_bar ?? null));
      if (listed.truncated || flagged.truncated) setExportError("The export was cut at 20,000 rows per source.");
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Export failed");
    }
  }

  if (error) return <p className="text-sm text-negative">Couldn&apos;t load the scorecard — {error.message}</p>;
  if (!data) {
    return (
      <div className="space-y-2" aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-9 animate-pulse rounded-md bg-surface-2" />
        ))}
      </div>
    );
  }

  const selected = data.versions.selected;
  const avail = data.versions.available;
  const banner = earlyBanner(data, horizon);
  const noData = !data.has_data;

  return (
    <div className="space-y-6">
      {noData && <p className="text-sm text-text-tertiary">No outcomes yet — the weekly routine job has not produced a priced list.</p>}
      {banner && !noData && (
        <p role="note" className="border-y border-border-subtle py-3 text-sm text-text-secondary">
          {banner}
        </p>
      )}

      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary">
              Sessions after entry
            </span>
            <SegmentedControl
              aria-label="Horizon"
              value={String(horizon)}
              onValueChange={(v) => setHorizon(Number(v))}
              options={HORIZON_OPTIONS.map((h) => ({ value: String(h), label: String(h) }))}
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary">Benchmark</span>
            <SegmentedControl
              aria-label="Benchmark"
              value={benchmark}
              onValueChange={(v) => setBenchmark(v as ScorecardBenchmark)}
              options={(["spy", "sector"] as const).map((b) => ({ value: b, label: BENCHMARK_LABEL[b] }))}
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => download(scorecardCsv(data), "text/csv", csvFileName("table", data.latest.outcomes_spy_bar))}
          >
            Export CSV
          </Button>
          <Button variant="outline" size="sm" onClick={exportOutcomes}>
            Export outcomes CSV
          </Button>
        </div>
      </div>
      {exportError && <p className="text-xs text-negative">{exportError}</p>}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-text-secondary">
        <label className="flex items-center gap-2">
          Weights version
          <Select
            size="short"
            aria-label="Weights version"
            value={filters.weightsVersion == null ? "all" : String(filters.weightsVersion)}
            onChange={(e) => setFilters((f) => ({ ...f, weightsVersion: e.target.value === "all" ? null : Number(e.target.value) }))}
          >
            <option value="all">All</option>
            {avail.weights.map((w) => (
              <option key={w} value={w}>
                v{w}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex items-center gap-2">
          Rules version
          <Select
            size="short"
            aria-label="Rules version"
            value={selected.rules}
            onChange={(e) => setFilters((f) => ({ ...f, rulesVersion: e.target.value === selected.current_rules ? null : e.target.value }))}
          >
            {[...new Set([selected.current_rules, ...avail.rules])].map((v) => (
              <option key={v} value={v}>
                v{v}
                {v === selected.current_rules ? " (current)" : ""}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex items-center gap-2">
          Triggers version
          <Select
            size="short"
            aria-label="Triggers version"
            value={selected.triggers}
            onChange={(e) => setFilters((f) => ({ ...f, triggersVersion: e.target.value === selected.current_triggers ? null : e.target.value }))}
          >
            {[...new Set([selected.current_triggers, ...avail.triggers])].map((v) => (
              <option key={v} value={v}>
                v{v}
                {v === selected.current_triggers ? " (current)" : ""}
              </option>
            ))}
          </Select>
        </label>
        {data.excluded.other_rules_version_rows > 0 && (
          <span>{data.excluded.other_rules_version_rows} rows from other rules versions are left out.</span>
        )}
        {data.excluded.cohorts_other_weights_version > 0 && <span>{data.excluded.cohorts_other_weights_version} lists on other weights versions are left out.</span>}
      </div>

      <Section>
        <p className="mb-3 text-xs text-text-tertiary">
          Excess is the return minus {BENCHMARK_NAME[benchmark]}&apos;s return over the same dates, {horizon} sessions after the entry open. Medians are taken per weekly
          list first, then across lists. Pending, censored and entry-gap rows are counted under n and left out of every figure; leveraged ETFs have their own row.
        </p>
        <ScorecardTable data={data} horizon={horizon} benchmark={benchmark} />
      </Section>

      <Section title="Flags">
        <p className="mb-3 text-xs text-text-tertiary">
          Flagged names are priced from the flag date; the comparison group is the same list&apos;s unflagged eligible names priced from the list date.{" "}
          <span className="text-text-secondary">{flags?.comparator_label ?? "Not a controlled comparison"}.</span> Names not covered or incomplete are kept out of the
          unflagged count. * Provisional while a window is open.
        </p>
        {flagsError && <p className="text-sm text-negative">Couldn&apos;t load the flags — {flagsError.message}</p>}
        {!flags && !flagsError && <div className="h-9 animate-pulse rounded-md bg-surface-2" aria-busy="true" />}
        {flags && (
          <div className="space-y-6">
            <FlagCountsTable flags={flags} horizon={horizon} benchmark={benchmark} />
            <FlagLedger flags={flags} horizon={horizon} benchmark={benchmark} />
          </div>
        )}
      </Section>

      <Section title="Picks">
        <PicksLine filters={filters} horizon={horizon} benchmark={benchmark} />
      </Section>

      <div className="space-y-1 text-xs text-text-tertiary">
        <p>
          Returns are price-only: dividends are not included. Entry is the first session&apos;s open after the list date; each horizon exits at that bar&apos;s close.
          Rules v{selected.rules} · triggers v{selected.triggers}
          {selected.weights != null ? ` · weights v${selected.weights}` : " · all weights versions"}
          {data.latest.outcomes_spy_bar ? ` · prices through ${data.latest.outcomes_spy_bar}` : ""}.
        </p>
        <p>Informational only — a frozen screen of stored data, not investment advice.</p>
      </div>
    </div>
  );
}
