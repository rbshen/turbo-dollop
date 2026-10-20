import type {
  FlagLedgerRow,
  ScorecardBenchmark,
  ScorecardCell,
  ScorecardGroup,
  ScorecardOut,
  ScorecardOutcomeRow,
  ScorecardState,
} from "@/lib/api/types";
import { fmtPct, pnlClass } from "@/lib/format";
import { LIST_LABEL, tierLabel } from "@/lib/opportunities";

// Pure helpers behind the Scorecard view (docs/specs/opportunities.md, "Scorecard"). Nothing here reads or writes the backend. Wording rule:
// never "beats the market", "works", a p-value, a ranking or a best-rule highlight; a cell below the gate shows counts and "—" only.

export const HORIZON_OPTIONS = [5, 10, 20, 60] as const;
export const BENCHMARK_LABEL: Record<ScorecardBenchmark, string> = { spy: "SPY", sector: "Sector ETF" };
export const BENCHMARK_NAME: Record<ScorecardBenchmark, string> = { spy: "SPY", sector: "its sector ETF" };

export const STATE_LABEL: Record<ScorecardState, string | null> = { too_early: "Too early", early: "Early", ok: null };
export const STATE_TITLE: Record<ScorecardState, string> = {
  too_early: "Below the gate (20 complete rows from at least 3 cohorts): counts only.",
  early: "Above the gate but still early (labelled Early until 60 complete rows from at least 8 cohorts).",
  ok: "",
};

export const RULE_LABEL: Record<string, string> = {
  B1: "B1 · Base or pending advance",
  B2: "B2 · Price structure",
  B3: "B3 · Entry signal",
  deep_pullback: "Deep pullback (Momentum)",
};

export const TRIGGER_LABEL: Record<string, string> = {
  D1: "D1 · Entry event",
  D2: "D2 · Stage upgrade",
  D3: "D3 · Pullback to the MA",
};

/** The row label of a group. Tier wording follows the tab: "Technical only" under Reversal, "Momentum-only" under Momentum (the stored key stays momentum_only). */
export function groupLabel(g: ScorecardGroup): string {
  if (g.kind === "rule") return RULE_LABEL[g.rule ?? ""] ?? g.rule ?? g.key;
  const list = g.list_name ?? "momentum";
  if (g.kind === "list") return `${LIST_LABEL[list]} list`;
  if (g.kind === "leveraged") return "Leveraged ETFs";
  return g.tier ? tierLabel(g.tier, list) : g.key;
}

export function cellOf(g: ScorecardGroup, horizon: number, benchmark: ScorecardBenchmark): ScorecardCell {
  return g.cells[String(horizon)][benchmark];
}

/** "+4.10%" / "−0.80%" with an explicit sign for a fraction (0.041), "—" when missing. */
export function fmtFrac(x: number | null | undefined, decimals = 2): string {
  if (x == null || Number.isNaN(x)) return "—";
  return fmtPct(x * 100, decimals);
}

/** "63%" for a share (0..1), "—" when missing. */
export function fmtShare(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${Math.round(x * 100)}%`;
}

/** Red/green only on a cell that is past "Early": below the gate and while early the figure is drawn neutral. */
export function excessClass(x: number | null | undefined, state: ScorecardState): string {
  if (x == null) return "text-text-tertiary";
  return state === "ok" ? pnlClass(x * 100) : "text-text-secondary";
}

/** "k of m cohorts positive". */
export function cohortsPositive(k: number, m: number): string {
  return `${k} of ${m}`;
}

export function weightsNote(cell: ScorecardCell): string | null {
  if (!cell.mixed_weights) return null;
  return `Spans score-weights versions ${cell.weights_versions.map((v) => `v${v}`).join(", ")}: the Quality tier depends on the weights, and the rows are not split by version here.`;
}

/** The sub-line under n: "2 pending · 1 censored · 1 entry gap". */
export function exclusionLine(c: { n_pending: number; n_censored: number; n_entry_gap: number; n_no_benchmark?: number; n_unpriced?: number }): string {
  const parts: string[] = [];
  if (c.n_pending) parts.push(`${c.n_pending} pending`);
  if (c.n_censored) parts.push(`${c.n_censored} censored`);
  if (c.n_entry_gap) parts.push(`${c.n_entry_gap} entry gap`);
  if (c.n_no_benchmark) parts.push(`${c.n_no_benchmark} no benchmark`);
  if (c.n_unpriced) parts.push(`${c.n_unpriced} not priced yet`);
  return parts.join(" · ");
}

function longDate(iso: string): string {
  return iso;
}

/** The early-data banner. Every date comes from the response. Null when some cell at this horizon is past the gate for every cohort-count
 * bar (nothing early left to say). */
export function earlyBanner(out: ScorecardOut, horizon: number): string | null {
  const { min_rows, min_cohorts, early_cohorts } = out.thresholds;
  let best = 0;
  for (const g of out.groups) {
    if (g.kind === "rule" || g.kind === "leveraged") continue;
    for (const b of out.benchmarks) best = Math.max(best, cellOf(g, horizon, b).cohorts);
  }
  if (best >= early_cohorts) return null;
  const done = out.cohorts.filter((c) => (c.horizons[String(horizon)]?.complete ?? 0) > 0).length;
  const parts = [
    `Early data: ${done} of ${out.cohorts.length} weekly ${out.cohorts.length === 1 ? "list has" : "lists have"} complete ${horizon}-session results${out.latest.outcomes_spy_bar ? ` (prices through ${longDate(out.latest.outcomes_spy_bar)})` : ""}.`,
    `A cell shows figures only with at least ${min_rows} complete rows from at least ${min_cohorts} weekly lists, and is labelled Early until ${out.thresholds.early_rows} rows from ${early_cohorts} lists.`,
  ];
  const next = out.next_expected[String(horizon)];
  if (next) parts.push(`The next ${horizon}-session results arrive with the ${longDate(next)} bar.`);
  return parts.join(" ");
}

// --- CSV ------------------------------------------------------------------------------------------------------------------------------

export function csvCell(v: unknown): string {
  if (v == null) return "";
  const s = typeof v === "object" ? JSON.stringify(v) : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(header: string[], rows: unknown[][]): string {
  return [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
}

/** The whole scorecard table, long format (every group x horizon x benchmark). Values are fractions; a gated cell has empty value columns. */
export function scorecardCsv(out: ScorecardOut): string {
  const header = [
    "group", "list", "tier", "rule", "horizon", "benchmark", "state", "n_complete", "n_pending", "n_censored", "n_entry_gap", "n_no_benchmark",
    "cohorts", "cohorts_total", "median_excess", "mean_excess", "share_above", "cohorts_positive", "benchmark_median_return", "median_return",
    "stop_hit_rate", "median_with_stop_return", "median_with_stop_excess", "median_worst_move", "median_drawdown", "median_excess_incl_censored",
    "pool_n_complete", "pool_cohorts", "pool_median_excess", "listed_minus_pool", "weights_versions", "mixed_weights", "rules_version",
  ];
  const rows: unknown[][] = [];
  for (const g of out.groups) {
    for (const h of out.horizons) {
      for (const b of out.benchmarks) {
        const c = g.cells[String(h)][b];
        const v = c.values;
        rows.push([
          groupLabel(g), g.list_name, g.tier, g.rule, h, b, c.state, c.n_complete, c.n_pending, c.n_censored, c.n_entry_gap, c.n_no_benchmark,
          c.cohorts, c.cohorts_total, v?.median_excess, v?.mean_excess, v?.share_above, v ? `${v.cohorts_positive}/${v.cohorts_counted}` : null,
          v?.benchmark_median_return, v?.median_return, v?.stop_hit_rate, v?.median_with_stop_return, v?.median_with_stop_excess, v?.median_worst_move,
          v?.median_drawdown, v?.including_censored.median_excess, c.pool?.n_complete, c.pool?.cohorts, c.pool?.values?.median_excess,
          c.listed_minus_pool?.median_excess, c.weights_versions.join("|"), c.mixed_weights, out.versions.selected.rules,
        ]);
      }
    }
  }
  return toCsv(header, rows);
}

const OUTCOME_COLUMNS = [
  "source", "cohort", "weights_version", "ticker", "list_name", "tier", "leveraged", "rules", "trigger_id", "flag_date", "horizon", "status",
  "censor_reason", "bucket", "entry_date", "exit_date", "entry_gap_pct", "entry_gap_flag", "forward_return", "spy_return", "excess_vs_spy",
  "sector_etf", "sector_return", "excess_vs_sector", "worst_move", "max_drawdown", "stop_hit", "stop_date", "stop_fill_return", "with_stop_return",
  "rules_version", "trigger_version",
];

/** The row-level audit as CSV: one line per outcome row with the bucket it was counted in (complete / pending / censored / entry_gap / leveraged / other_version). */
export function outcomesCsv(rows: ScorecardOutcomeRow[]): string {
  return toCsv(OUTCOME_COLUMNS, rows.map((r) => OUTCOME_COLUMNS.map((c) => (Array.isArray(r[c]) ? (r[c] as unknown[]).join("|") : r[c]))));
}

export function csvFileName(kind: "table" | "outcomes", asOf: string | null): string {
  return `scorecard-${kind}${asOf ? `-${asOf}` : ""}.csv`;
}

// --- flags ledger -----------------------------------------------------------------------------------------------------------------------

export interface LedgerCells {
  ret: number | null;
  excess: number | null;
  stop: string;
  status: string;
}

/** One ledger line at the chosen horizon and benchmark: return, excess, and the stop ("Stopped −10.0%" / "No stop" / "—" while pending without a hit). */
export function ledgerCells(row: FlagLedgerRow, horizon: number, benchmark: ScorecardBenchmark): LedgerCells {
  const h = row.horizons[String(horizon)];
  if (!h) return { ret: null, excess: null, stop: "—", status: "not priced yet" };
  const stop = h.stop_hit ? `Stopped ${fmtFrac(h.stop_fill_return, 1)}` : h.status === "complete" ? "No stop" : "—";
  return {
    ret: h.status === "complete" || h.status === "censored" ? h.forward_return : null,
    excess: h.status === "complete" ? (benchmark === "spy" ? h.excess_vs_spy : h.excess_vs_sector) : null,
    stop,
    status: h.status,
  };
}
