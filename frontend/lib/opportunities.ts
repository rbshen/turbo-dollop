import type {
  OpportunityListName,
  OpportunityRowOut,
  OpportunityRunOut,
  OpportunityTier,
} from "@/lib/api/types";
import { verdictLabel } from "@/lib/tierColor";
import { WEINSTEIN_STAGE_LABEL, type WeinsteinStage } from "@/lib/weinsteinStage";

// Pure helpers behind the Opportunities page (docs/specs/opportunities.md). Nothing here reads or writes the backend.

export type TierFilter = "all" | OpportunityTier;

export const TIER_FILTER_OPTIONS: { value: TierFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "quality", label: "Quality" },
  { value: "momentum_only", label: "Momentum-only" },
  { value: "etf", label: "ETF" },
];

export const TIER_LABEL: Record<OpportunityTier, string> = {
  quality: "Quality",
  momentum_only: "Momentum-only",
  etf: "ETF",
};

/** The tier word as drawn on a given tab. The stored value is "momentum_only" everywhere; on the Reversal tab alone the second tier
 * reads "Technical only" (its stocks are there for the chart, not the fundamentals). Display only. */
export function tierLabel(tier: OpportunityTier, list: OpportunityListName): string {
  return list === "reversal" && tier === "momentum_only" ? "Technical only" : TIER_LABEL[tier];
}

/** The segmented control's options for a tab, with the tab's own tier wording. */
export function tierFilterOptions(list: OpportunityListName): { value: TierFilter; label: string }[] {
  return TIER_FILTER_OPTIONS.map((o) => (o.value === "all" ? o : { ...o, label: tierLabel(o.value, list) }));
}

export const LIST_LABEL: Record<OpportunityListName, string> = { momentum: "Momentum", reversal: "Reversal" };

export function rowsFor(run: OpportunityRunOut, list: OpportunityListName): OpportunityRowOut[] {
  return list === "momentum" ? run.momentum : run.reversal;
}

export function filterByTier(rows: OpportunityRowOut[], tier: TierFilter): OpportunityRowOut[] {
  return tier === "all" ? rows : rows.filter((r) => r.tier === tier);
}

/** Row count per segment of one list (the segmented control's counts). */
export function tierCounts(rows: OpportunityRowOut[]): Record<TierFilter, number> {
  const counts: Record<TierFilter, number> = { all: rows.length, quality: 0, momentum_only: 0, etf: 0 };
  for (const r of rows) counts[r.tier] += 1;
  return counts;
}

/** The rank column's tooltip: which group the rank is within (a rank means nothing without its universe). */
export function rankTitle(row: OpportunityRowOut): string | undefined {
  if (row.momentum_rank == null) return undefined;
  const size = row.inputs.momentum_group_size;
  const group = row.inputs.momentum_group;
  const noun = group === "leveraged_etfs" ? "leveraged ETFs" : group === "etfs" ? "ETFs" : "stocks";
  return size ? `Momentum rank ${row.momentum_rank} of ${size} ${noun} (3, 6 and 12 month composite)` : `Momentum rank ${row.momentum_rank}`;
}

/** "$1,234M" style column: average daily dollar volume in millions, "—" when unknown. */
export function fmtAdvM(adv: number | null): string {
  if (adv == null) return "—";
  return Math.round(adv / 1e6).toLocaleString("en-US");
}

export interface TagPill {
  key: string;
  label: string;
  title?: string;
  tone: "neutral" | "warn";
}

function stageName(stage: string | null | undefined): string {
  return stage && stage in WEINSTEIN_STAGE_LABEL ? WEINSTEIN_STAGE_LABEL[stage as WeinsteinStage] : "no stage";
}

const MOAT_WORDS: Record<string, string> = { wide_moat: "Wide moat", narrow_moat: "Narrow moat", no_moat: "No moat" };

/** The stored tags as pills, in a fixed order. `list` decides which of them apply to the tab (the signal-coverage pill is a
 * Reversal-tab note; "also on" points at the other list). Display wording only: the stored verdict key "Fail" reads "May not pass". */
export function tagPills(row: OpportunityRowOut, list: OpportunityListName): TagPill[] {
  const t = row.tags;
  const pills: TagPill[] = [];
  if (t.late_trend) {
    pills.push({
      key: "late",
      label: "Late trend",
      title: `${row.weeks_in_advance ?? "52+"} weeks in Advance (a trend this old is late, not new)`,
      tone: "warn",
    });
  }
  if (t.leveraged) {
    pills.push({ key: "lev", label: `${t.leveraged}x leveraged`, title: "Leveraged fund: ranked apart from ordinary ETFs", tone: "warn" });
  }
  if (t.held_back_by_moat) {
    pills.push({
      key: "moat",
      label: "Held back by moat",
      title: `Fundamentals ${row.steps_score != null ? row.steps_score.toFixed(1) : "70+"} but Overall ${row.overall_score ?? "—"}: only the Moat multiplier keeps it under 70`,
      tone: "neutral",
    });
  }
  if (t.why_not_quality) {
    const w = t.why_not_quality;
    const verdict = w.overall_verdict ? verdictLabel(w.overall_verdict) : "Incomplete";
    const parts = [`Overall: ${verdict}`];
    if (w.failed_steps.length) parts.push(`below the pass line: ${w.failed_steps.join(", ")}`);
    if (w.incomplete_steps.length) parts.push(`incomplete: ${w.incomplete_steps.join(", ")}`);
    parts.push(w.moat ? MOAT_WORDS[w.moat] ?? w.moat : "Moat not rated");
    const extra = w.failed_steps.length > 1 ? ` +${w.failed_steps.length - 1}` : "";
    // On the Reversal tab the tier is "Technical only", so the tag says what is missing: the fundamentals.
    const label =
      list === "reversal"
        ? `Fundamentals not passed${w.failed_steps.length ? `: ${w.failed_steps[0]}${extra}` : ""}`
        : w.failed_steps.length
          ? `Not quality: ${w.failed_steps[0]}${extra}`
          : `Not quality: ${verdict}`;
    pills.push({ key: "wnq", label, title: parts.join(" · "), tone: "neutral" });
  }
  if (t.deep_pullback) {
    const dd = row.inputs.drawdown_pct;
    pills.push({
      key: "pullback",
      label: "Deep pullback",
      title: `An established uptrend whose chart passes the reversal price-structure test${typeof dd === "number" ? ` (${dd.toFixed(0)}% below its 52-week high)` : ""}`,
      tone: "neutral",
    });
  }
  if (list === "reversal" && t.signal_status === "not_covered") {
    pills.push({
      key: "cov",
      label: "Signals not covered",
      title: "Not on a monitored watchlist, so the Warren and BB+RSI signal jobs never ran for it: this is not a 'no signal'",
      tone: "neutral",
    });
  }
  if (t.sector) {
    const s = t.sector;
    const breadth = s.breadth ? ` · ${s.breadth.pct_above_sma50?.toFixed(0) ?? "—"}% above 50-day · net new highs ${s.breadth.net_new_highs > 0 ? "+" : ""}${s.breadth.net_new_highs}` : "";
    pills.push({
      key: "sector",
      label: `${s.etf} ${s.stage ? stageName(s.stage).split(" · ")[1] : "—"}`,
      title: `${s.name}: ${s.etf} is in ${stageName(s.stage)}${s.momentum_rank != null ? ` · momentum rank ${s.momentum_rank} of ${s.momentum_group_size}` : ""}${breadth}`,
      tone: "neutral",
    });
  }
  return pills;
}

export const MAX_TAG_PILLS = 3;

// --- exports ---------------------------------------------------------------------------------------------------------------

/** thinkorswim's import takes bare symbols, one per line (the same shape as the Watchlist export). */
export function thinkorswimText(rows: OpportunityRowOut[]): string {
  return rows.map((r) => `${r.ticker}\n`).join("");
}

/** `opportunities-<list>-<selection|view>-<as_of>[_thinkorswim].<ext>`: says whether the file is the ticked rows ("selection") or
 * everything in the current tab and tier filter ("view"). A selection that spans both lists names both (`momentum-reversal`). */
export function exportFileName(lists: OpportunityListName[], scope: ExportScope, asOf: string, ext: "txt" | "csv"): string {
  return `opportunities-${lists.join("-")}-${scope}-${asOf}${ext === "csv" ? "_thinkorswim" : ""}.${ext}`;
}

export type ExportScope = "selection" | "view";

/** What the TradingView builder needs from a row: an ETF has no GICS sector (it lands in "Other"). */
export function exportRows(rows: OpportunityRowOut[]) {
  return rows.map((r) => ({ ticker: r.ticker, exchange: r.exchange, sector: r.tier === "etf" ? null : r.sector }));
}

// --- row selection (held by ticker; a ticker is on one list per run, so a ticker names exactly one row) ---------------------------

/** The selection after clicking `ticker`'s checkbox. A plain click flips that ticker. With `shift` and an `anchor` that is among the
 * `shown` tickers, every shown row from the anchor to `ticker` is set to the state the clicked row is moving to. */
export function toggleSelection(
  selected: ReadonlySet<string>,
  shown: string[],
  ticker: string,
  anchor: string | null,
  shift: boolean,
): Set<string> {
  const next = new Set(selected);
  const turnOn = !selected.has(ticker);
  const from = shift && anchor !== null ? shown.indexOf(anchor) : -1;
  const to = shown.indexOf(ticker);
  const span = from >= 0 && to >= 0 ? shown.slice(Math.min(from, to), Math.max(from, to) + 1) : [ticker];
  for (const t of span) {
    if (turnOn) next.add(t);
    else next.delete(t);
  }
  return next;
}

/** The header checkbox: every shown row selected -> deselect the shown rows; otherwise select them all. Tickers selected but not shown
 * (another tier filter or tab) are left as they are. */
export function toggleAllShown(selected: ReadonlySet<string>, shown: string[]): Set<string> {
  const next = new Set(selected);
  const all = shown.length > 0 && shown.every((t) => selected.has(t));
  for (const t of shown) {
    if (all) next.delete(t);
    else next.add(t);
  }
  return next;
}
