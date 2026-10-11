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
    pills.push({
      key: "wnq",
      label: w.failed_steps.length ? `Not quality: ${w.failed_steps[0]}${w.failed_steps.length > 1 ? ` +${w.failed_steps.length - 1}` : ""}` : `Not quality: ${verdict}`,
      title: parts.join(" · "),
      tone: "neutral",
    });
  }
  if (t.also_on) {
    pills.push({ key: "also", label: `Also on ${t.also_on}`, title: `This ticker is also on the ${LIST_LABEL[t.also_on]} list`, tone: "neutral" });
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

export function exportFileName(list: OpportunityListName, asOf: string, ext: "txt" | "csv"): string {
  return `opportunities-${list}-${asOf}${ext === "csv" ? "_thinkorswim" : ""}.${ext}`;
}

/** What the TradingView builder needs from a row: an ETF has no GICS sector (it lands in "Other"). */
export function exportRows(rows: OpportunityRowOut[]) {
  return rows.map((r) => ({ ticker: r.ticker, exchange: r.exchange, sector: r.tier === "etf" ? null : r.sector }));
}
