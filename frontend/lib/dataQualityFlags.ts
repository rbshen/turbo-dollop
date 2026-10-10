// Wording and grouping for the stored cache-only data-quality flags (backend scoring/data_quality.py, docs/specs/data-quality.md).
// Sentence case, plain words, no verdict language: these are informational notes about FMP's rows and feed no score.
import { fmtCompactMoney } from "@/lib/format";
import type { DataQualityFlagOut, DataQualityKind } from "@/lib/api/types";

export const CHECK_LABELS: Record<string, string> = {
  zero_newest_capex: "Zero newest capex",
  sbc_gap: "Stock compensation gap",
  net_income_disagreement: "Net income disagreement",
};

export const FIELD_LABELS: Record<string, string> = {
  capitalExpenditure: "Capex",
  stockBasedCompensation: "Stock-based compensation",
  netIncome: "Net income",
};

export const KIND_LABELS: Record<DataQualityKind, string> = {
  zero_line: "Line missing",
  zero_between: "Zero between years",
  zero_newest: "Zero in newest year",
  sign_differs: "Opposite signs",
  large_gap: "Large gap",
  definition: "Definition difference",
};

/** What the second figure is, for the hover text on the comparison column. */
export const COMPARISON_LABELS: Record<string, string> = {
  zero_newest_capex: "Capex in the prior fiscal year",
  sbc_gap: "Stock-based compensation in the nearest non-zero year",
  net_income_disagreement: "Net income on the cash-flow statement (the first figure is the income statement's)",
};

export function checkLabel(check: string): string {
  return CHECK_LABELS[check] ?? check;
}

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind as DataQualityKind] ?? kind;
}

export function fmtFlagValue(value: number | null): string {
  return value === null ? "—" : fmtCompactMoney(value);
}

/** Found date as the plain ISO day, like every other date in the tables. */
export function foundDate(found_at: string): string {
  return found_at.slice(0, 10);
}

export const NOTE_MAX_LINES = 3;

export interface NoteLine {
  key: string;
  text: string;
}

/** The ticker-page note: at most three lines, the most important findings first (the API already orders them). Several stock-compensation
 * flags for one ticker (one per fiscal year) read as a single line; when more lines remain than fit, the last line says how many. */
export function noteLines(flags: DataQualityFlagOut[] | undefined): NoteLine[] {
  if (!flags || flags.length === 0) return [];
  const lines: NoteLine[] = [];
  const sbc = flags.filter((f) => f.check === "sbc_gap");
  for (const flag of flags) {
    if (flag.check === "sbc_gap") {
      if (flag !== sbc[0]) continue;
      if (sbc.length === 1) {
        lines.push({ key: String(flag.id), text: flag.detail });
      } else {
        const years = sbc.map((f) => `FY${f.fiscal_year}`).sort().join(", ");
        lines.push({ key: String(flag.id), text: `Stock-based compensation reads 0 for ${years}, so SBC totals may be understated.` });
      }
      continue;
    }
    lines.push({ key: String(flag.id), text: flag.detail });
  }
  if (lines.length <= NOTE_MAX_LINES) return lines;
  const hidden = lines.length - (NOTE_MAX_LINES - 1);
  return [...lines.slice(0, NOTE_MAX_LINES - 1), { key: "more", text: `${hidden} more in Settings > Data quality.` }];
}
