// Display wording and column matching for the read-time data-quality flags (backend
// helpers/statement_view.py::data_quality_flags, docs/specs/statement-data-quality.md "Display markers"). The backend
// sends facts; every sentence a reader sees is here. Markers never change a value: they only annotate it.

import type { DataQualityFlag } from "@/lib/api/types";

export const PLACEHOLDER_CELL_MESSAGE = "No cash flow reported for this period — $0 is a placeholder, not a result.";
export const PLACEHOLDER_TTM_MESSAGE =
  "TTM sums the last four quarters as returned, including a placeholder quarter, so it is understated. The Analysis tab uses the last four valid quarters.";
export const SCALE_BREAK_TTM_MESSAGE =
  "TTM sums the last four quarters as returned, including a quarter derived from a row in a different unit, so it is misstated. The Analysis tab skips that quarter.";
export const SCALE_BREAK_MESSAGE = "This row is in a different unit from its neighbours; scores ignore it.";
export const SCALE_BREAK_DERIVED_MESSAGE =
  "This quarter is derived from a row in a different unit; scores ignore it.";
export const RATIOS_FROM_FMP_MESSAGE =
  "These ratios are computed by FMP and may be built from an incomplete newest quarter.";

export type StatementKind = "income" | "balance_sheet" | "cash_flow";

/** The date the Analysis tab falls back to, for a partial-balance-sheet flag. */
export function usedQuarterDate(flag: DataQualityFlag): string | null {
  const used = flag.detail?.used_quarter_date;
  return typeof used === "string" ? used : null;
}

export function partialBalanceSheetMessage(flag: DataQualityFlag): string {
  const used = usedQuarterDate(flag);
  return used
    ? `Newest balance sheet looks incomplete; the Analysis tab uses ${used}.`
    : "Newest balance sheet looks incomplete; the Analysis tab uses the prior quarter.";
}

export function notLandedMessage(flag: DataQualityFlag): string {
  const reported = flag.detail?.reported_on;
  return `Latest earnings (${typeof reported === "string" ? reported : "date unknown"}) are not in the statements yet.`;
}

function byRule(flags: DataQualityFlag[] | undefined, rule: DataQualityFlag["rule"]): DataQualityFlag[] {
  return (flags ?? []).filter((f) => f.rule === rule);
}

export function partialBalanceSheetFlag(flags: DataQualityFlag[] | undefined): DataQualityFlag | undefined {
  return byRule(flags, "partial_balance_sheet")[0];
}

export function notLandedFlag(flags: DataQualityFlag[] | undefined): DataQualityFlag | undefined {
  return byRule(flags, "not_landed")[0];
}

/** The Ratios tab and the Step 4 ROIC/ROE display: FMP computes these from the newest quarter, so the note shows when the
 * balance-sheet gate fired or a placeholder or scale break sits on the newest row of its series. Never for not_landed
 * alone (nothing is wrong with the rows that are there). */
export function showsFmpRatiosNote(flags: DataQualityFlag[] | undefined): boolean {
  return (flags ?? []).some(
    (f) =>
      f.rule === "partial_balance_sheet" ||
      ((f.rule === "placeholder_cf" || f.rule === "scale_break") && f.detail?.newest_period === true),
  );
}

export interface ColumnMarker {
  message: string;
  evidence: string;
}

const isTtmLabel = (label: string) => label.startsWith("TTM");

/** Markers for one column of one Financials table. `column` is the table's period label; the annual table's last column is
 * its TTM column. A flag lands on its own period column (matched on the label the backend echoed) and, when its row is in
 * the raw TTM window, on the annual table's TTM column. */
export function columnMarkers(
  flags: DataQualityFlag[] | undefined,
  statement: StatementKind,
  periodType: "annual" | "quarterly",
  column: string,
): ColumnMarker[] {
  const out: ColumnMarker[] = [];
  const ttmColumn = periodType === "annual" && isTtmLabel(column);
  for (const flag of flags ?? []) {
    if (flag.statement !== statement || flag.rule === "not_landed") continue;
    const inTtm = flag.detail?.in_ttm_window === true;
    const onOwnColumn = flag.period === periodType && flag.column != null && flag.column === column;
    if (!onOwnColumn && !(ttmColumn && inTtm)) continue;
    if (flag.rule === "placeholder_cf") {
      out.push({ message: ttmColumn ? PLACEHOLDER_TTM_MESSAGE : PLACEHOLDER_CELL_MESSAGE, evidence: flag.evidence });
    } else if (flag.rule === "scale_break") {
      const derived = flag.detail?.derived_q4 === true;
      out.push({
        message: ttmColumn ? SCALE_BREAK_TTM_MESSAGE : derived ? SCALE_BREAK_DERIVED_MESSAGE : SCALE_BREAK_MESSAGE,
        evidence: flag.evidence,
      });
    } else if (flag.rule === "partial_balance_sheet") {
      out.push({ message: partialBalanceSheetMessage(flag), evidence: flag.evidence });
    }
  }
  return out;
}
