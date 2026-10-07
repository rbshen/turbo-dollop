"use client";

import { AnalysisSectionCard, type ReasoningBullet, weightScoreSuffix } from "@/components/shared/AnalysisSectionCard";
import { useStep1 } from "@/lib/hooks/useStep1";
import type { Step1Out } from "@/lib/api/types";

const METHODOLOGY =
  "A weighted blend of Revenue, Net Income, Cash Flow from Operations, Margins, and Free Cash Flow scores " +
  "(Revenue, Net Income, and Margins alone when CFO/FCF don't apply), banded 0–69 Fail / 70–90 Pass / " +
  "91–100 Strong Pass. Each is scored from its last 5–10 completed fiscal years (never the trailing twelve months) on one " +
  "neutral trend assessment: long-term direction, a graduated penalty for dips (more, longer or unrecovered dips cost more), " +
  "and a cut for a fresh fall in the last fiscal year. Margins is the lower of gross margin and the better of net and " +
  "operating margin; a margin at or below zero in the latest year is capped.";

interface Props {
  ticker: string;
}

// Order mirrors scoring/step1.py::score_step1's components dict -- every component carries one of the six
// scoring/step1_engine.py labels (or not_yet_positive / insufficient_data), see docs/specs/financials.md.
const METRIC_ORDER = ["revenue", "net_income", "cfo", "margins", "fcf"] as const;

const STATIC_METRIC_LABELS: Record<string, string> = {
  net_income: "Net Income",
  cfo: "Cash Flow from Operations",
  margins: "Margins",
  fcf: "Free Cash Flow",
};

// Shorter labels for the "aren't scored" exemption note specifically --
// deliberately not STATIC_METRIC_LABELS (that map's "Cash Flow from
// Operations" reads fine as a per-bullet label but is more verbose than
// this sentence needs).
const EXEMPTION_NOTE_METRIC_LABELS: Record<string, string> = {
  cfo: "Cash Flow",
  fcf: "Free Cash Flow",
  margins: "Margins",
};

export const TIER_LABELS: Record<string, string> = {
  insufficient_data: "Insufficient data",
  // The Revenue / Net Income / CFO positivity gate (scoring/step1.py)
  not_yet_positive: "Not yet positive",
  // scoring/step1_engine.py: long-term direction, with "_dips" when the dip burden is 0.25 or more
  uptrend: "Growing",
  uptrend_dips: "Growing, with dips",
  flat: "Flat",
  flat_dips: "Flat, with dips",
  decline: "Declining",
  decline_dips: "Declining, with dips",
};

function tierClass(score: number): string {
  if (score === 0) return "text-negative";
  if (score < 70) return "text-warn";
  return "text-text-primary";
}

function metricLabel(key: string, data: Step1Out): string {
  if (key === "revenue") return data.revenue_label;
  return STATIC_METRIC_LABELS[key] ?? key;
}

function joinWithAnd(items: string[]): string {
  if (items.length <= 1) return items.join("");
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

// Financials has no hard-fail concept (score_step1 is a pure weighted
// blend against the shared 0-69/70-90/91-100 bands, unlike Debt/
// Profitability's hard-fail overrides) -- so the verdict sentence names
// whichever components actually scored below the Pass threshold, using
// data already computed for the bullets below, rather than restating the
// weighting scheme (see git history: 89b1728 fixed a misleading "N of 5
// must pass" framing but left the blurb as pure methodology text with no
// verdict at all -- this restores a real verdict, worded from the actual
// per-component scores instead).
function verdictSentence(componentRows: { label: string; score: number }[], verdict: string): string {
  const weak = componentRows.filter((row) => row.score < 70).map((row) => row.label);
  if (weak.length === 0) {
    return `All components (${joinWithAnd(componentRows.map((row) => row.label))}) cleared the Pass threshold — none pulled the blend down.`;
  }
  if (verdict === "Fail") {
    return `${joinWithAnd(weak)} scored below the Pass threshold, pulling the blend down to a Fail.`;
  }
  return `${joinWithAnd(weak)} scored below the Pass threshold, but the rest of the blend was strong enough to still reach a ${verdict}.`;
}

// Built from whichever of {cfo, fcf, margins} actually come back null in
// `data.components`, rather than a fixed "Cash Flow and Free Cash Flow"
// string -- Banks (2026-09-10) exclude Margins too, on top of CFO/FCF, so
// this needs to read correctly for 2 items (every other exempt type:
// Insurance, Property Developer, Commodity Company) and 3 (Banks) alike,
// including the isn't/aren't agreement.
export function exemptionNote(data: Step1Out): string | null {
  if (!data.cfo_exempt_reason) return null;
  const excluded = METRIC_ORDER.filter((key) => key in EXEMPTION_NOTE_METRIC_LABELS)
    .filter((key) => !data.components[key as keyof typeof data.components])
    .map((key) => EXEMPTION_NOTE_METRIC_LABELS[key]);
  if (excluded.length === 0) return null;
  const verb = excluded.length === 1 ? "isn't" : "aren't";
  return `${joinWithAnd(excluded)} ${verb} scored for this company — classified as a ${data.cfo_exempt_reason}.`;
}

// The Net Income card note, shown only when the Operating Income backup actually changed the score
// (scoring/step1.py sets used_operating_income_backup and the two extra fields in that case alone).
export function backupNote(data: Step1Out): { text: string; tooltip: string } | null {
  const ni = data.components.net_income;
  if (!ni.used_operating_income_backup) return null;
  const gates = ni.backup_gates;
  const gateText = gates
    ? ` Backup gates: last fiscal year Operating Income margin ${gates.oi_margin_pct == null ? "n/a" : `${gates.oi_margin_pct}%`} ` +
      `(needs at least ${gates.min_oi_margin_pct}%), positive in ${gates.positive_periods} of the last ${gates.window} fiscal years ` +
      `(needs at least ${gates.min_positive_periods}).`
    : "";
  const liftText = ni.score_before_backup == null ? "" : ` Net Income score ${ni.score_before_backup} lifted to ${ni.score}.`;
  return {
    text: "Score lifted using Operating Income (backup)",
    tooltip:
      "Net Income was inconsistent, which can be distorted by one-offs, so the score uses Operating Income, " +
      `which strips them out.${liftText}${gateText}`,
  };
}

export function Step1Card({ ticker }: Props) {
  const { data, error } = useStep1(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-negative">Couldn&apos;t load Financials data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Financials…</p>
      </div>
    );
  }

  if (data.verdict === "insufficient_data" || data.score == null) {
    return (
      <div className="space-y-2 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Financials</h2>
        <p className="text-sm text-text-tertiary">Required figures were unavailable for {ticker}.</p>
      </div>
    );
  }

  const componentRows = METRIC_ORDER.map((key) => {
    const component = data.components[key as keyof typeof data.components];
    if (!component) return null;
    return {
      key,
      label: metricLabel(key, data),
      tierLabel: TIER_LABELS[component.pattern] ?? component.pattern,
      score: component.score,
    };
  }).filter((row): row is NonNullable<typeof row> => row !== null);

  const blurb = verdictSentence(componentRows, data.verdict);

  // Weight + score shown per-bullet (not the top-line verdict sentence
  // above) -- stays correct for the CFO/FCF-exempt redistribution case too
  // (Bank/Insurance/Property Developer/Commodity tickers), since weight
  // reads straight from data.weights rather than a static percentage.
  const note = backupNote(data);
  const bullets: ReasoningBullet[] = componentRows.flatMap((row) => {
    const bullet: ReasoningBullet = {
      key: row.key,
      text: `${row.label}${weightScoreSuffix(data.weights[row.key], row.score)}: ${row.tierLabel}`,
      tierClassName: tierClass(row.score),
    };
    if (row.key !== "net_income" || !note) return [bullet];
    return [bullet, { key: "net_income-backup-note", text: `↳ ${note.text}`, tierClassName: "text-text-tertiary", tooltip: note.tooltip }];
  });

  const exemptionNoteText = exemptionNote(data);
  const notes = exemptionNoteText ? <p className="text-xs text-text-tertiary">{exemptionNoteText}</p> : null;

  return (
    <AnalysisSectionCard
      title="Financials"
      score={data.score}
      verdict={data.verdict}
      blurb={blurb}
      methodology={METHODOLOGY}
      notes={notes}
      bullets={bullets}
    />
  );
}
