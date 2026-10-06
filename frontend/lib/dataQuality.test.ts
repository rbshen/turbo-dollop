import { describe, expect, it } from "vitest";

import type { DataQualityFlag } from "@/lib/api/types";
import {
  PLACEHOLDER_CELL_MESSAGE,
  PLACEHOLDER_TTM_MESSAGE,
  SCALE_BREAK_DERIVED_MESSAGE,
  SCALE_BREAK_MESSAGE,
  SCALE_BREAK_TTM_MESSAGE,
  columnMarkers,
  notLandedMessage,
  partialBalanceSheetMessage,
  showsFmpRatiosNote,
} from "@/lib/dataQuality";

const flag = (over: Partial<DataQualityFlag>): DataQualityFlag => ({
  rule: "placeholder_cf",
  statement: "cash_flow",
  period: "quarterly",
  period_end: "2026-06-30",
  column: "Q4 2026",
  evidence: "all cash-flow section totals are 0 while net income is 100",
  detail: {},
  ...over,
});

describe("columnMarkers", () => {
  it("marks a placeholder quarter on its own column with the placeholder sentence and the evidence", () => {
    const flags = [flag({ detail: { in_ttm_window: true } })];

    expect(columnMarkers(flags, "cash_flow", "quarterly", "Q4 2026")).toEqual([
      { message: PLACEHOLDER_CELL_MESSAGE, evidence: "all cash-flow section totals are 0 while net income is 100" },
    ]);
    expect(columnMarkers(flags, "cash_flow", "quarterly", "Q3 2026")).toEqual([]);
  });

  it("marks the annual TTM column when a placeholder quarter is inside the raw TTM window", () => {
    const flags = [flag({ detail: { in_ttm_window: true } })];

    const markers = columnMarkers(flags, "cash_flow", "annual", "TTM (2026-06-30)");

    expect(markers.map((m) => m.message)).toEqual([PLACEHOLDER_TTM_MESSAGE]);
  });

  it("does not mark the TTM column for a placeholder outside the window, nor a different statement", () => {
    const old = [flag({ detail: { in_ttm_window: false } })];

    expect(columnMarkers(old, "cash_flow", "annual", "TTM (2026-06-30)")).toEqual([]);
    expect(columnMarkers([flag({ detail: { in_ttm_window: true } })], "income", "annual", "TTM (2026-06-30)")).toEqual([]);
    expect(columnMarkers([flag({ detail: { in_ttm_window: true } })], "balance_sheet", "annual", "TTM (2026-06-30)")).toEqual([]);
  });

  it("marks an annual placeholder or scale-broken row on its own annual column only", () => {
    const annual = [
      flag({ rule: "scale_break", period: "annual", column: "2026-06-30", evidence: "12 lines are about 1,000 times off", detail: { derived_q4: false } }),
    ];

    expect(columnMarkers(annual, "cash_flow", "annual", "2026-06-30").map((m) => m.message)).toEqual([SCALE_BREAK_MESSAGE]);
    expect(columnMarkers(annual, "cash_flow", "annual", "2025-06-30")).toEqual([]);
    expect(columnMarkers(annual, "cash_flow", "annual", "TTM (2026-06-30)")).toEqual([]);
  });

  it("words the poisoned Q4 of a scale-broken year differently on its column and in the TTM", () => {
    const derived = [flag({ rule: "scale_break", detail: { derived_q4: true, in_ttm_window: true } })];

    expect(columnMarkers(derived, "cash_flow", "quarterly", "Q4 2026").map((m) => m.message)).toEqual([SCALE_BREAK_DERIVED_MESSAGE]);
    expect(columnMarkers(derived, "cash_flow", "annual", "TTM (2026-06-30)").map((m) => m.message)).toEqual([SCALE_BREAK_TTM_MESSAGE]);
  });

  it("marks a partial balance sheet on its newest-quarter column and the TTM column, naming the date used", () => {
    const partial = flag({
      rule: "partial_balance_sheet",
      statement: "balance_sheet",
      evidence: "total debt 9,045 -> 190 (-98%) while total liabilities moved 11,921 -> 11,929",
      detail: { reason: "debt_remap", used_quarter_date: "2026-03-31", in_ttm_window: true },
    });
    const message = "Newest balance sheet looks incomplete; the Analysis tab uses 2026-03-31.";

    expect(columnMarkers([partial], "balance_sheet", "quarterly", "Q4 2026").map((m) => m.message)).toEqual([message]);
    expect(columnMarkers([partial], "balance_sheet", "annual", "TTM (2026-06-30)").map((m) => m.message)).toEqual([message]);
    expect(columnMarkers([partial], "balance_sheet", "annual", "2025-06-30")).toEqual([]);
    expect(partialBalanceSheetMessage(partial)).toBe(message);
  });

  it("never marks a column for not_landed", () => {
    const landed = flag({ rule: "not_landed", statement: "income", detail: { reported_on: "2026-08-04" } });

    expect(columnMarkers([landed], "income", "quarterly", "Q4 2026")).toEqual([]);
    expect(notLandedMessage(landed)).toBe("Latest earnings (2026-08-04) are not in the statements yet.");
  });

  it("tolerates a payload with no flags", () => {
    expect(columnMarkers(undefined, "cash_flow", "annual", "TTM (2026-06-30)")).toEqual([]);
  });
});

describe("showsFmpRatiosNote", () => {
  it("shows when the balance-sheet gate fired", () => {
    expect(showsFmpRatiosNote([flag({ rule: "partial_balance_sheet", statement: "balance_sheet" })])).toBe(true);
  });

  it("shows for a placeholder or scale break on a newest-period row, not on an older one", () => {
    expect(showsFmpRatiosNote([flag({ detail: { newest_period: true } })])).toBe(true);
    expect(showsFmpRatiosNote([flag({ rule: "scale_break", detail: { newest_period: true } })])).toBe(true);
    expect(showsFmpRatiosNote([flag({ detail: { newest_period: false } })])).toBe(false);
  });

  it("is not shown for not_landed alone, nor with no flags", () => {
    expect(showsFmpRatiosNote([flag({ rule: "not_landed", statement: "income" })])).toBe(false);
    expect(showsFmpRatiosNote([])).toBe(false);
    expect(showsFmpRatiosNote(undefined)).toBe(false);
  });
});
