import { describe, expect, it } from "vitest";

import type { DataQualityFlagOut } from "@/lib/api/types";
import { checkLabel, fieldLabel, fmtFlagValue, foundDate, kindLabel, noteLines } from "@/lib/dataQualityFlags";

function flag(over: Partial<DataQualityFlagOut>): DataQualityFlagOut {
  return {
    id: 1,
    ticker: "MU",
    check: "zero_newest_capex",
    field: "capitalExpenditure",
    fiscal_year: "2026",
    fmp_value: 0,
    comparison_value: -15857000000,
    kind: "zero_line",
    detail: "FY2026 capex is 0 in the newest row, so free cash flow may be overstated.",
    found_at: "2026-10-10T03:26:00",
    last_seen_at: "2026-10-10T03:26:00",
    reviewed_at: null,
    ...over,
  };
}

describe("labels", () => {
  it("are sentence case and fall back to the raw key", () => {
    expect(checkLabel("zero_newest_capex")).toBe("Zero newest capex");
    expect(checkLabel("sbc_gap")).toBe("Stock compensation gap");
    expect(fieldLabel("capitalExpenditure")).toBe("Capex");
    expect(kindLabel("definition")).toBe("Definition difference");
    expect(kindLabel("something_new")).toBe("something_new");
  });

  it("formats values compactly and a missing one as a dash", () => {
    expect(fmtFlagValue(-15857000000)).toBe("-$15.86B");
    expect(fmtFlagValue(0)).toBe("$0.00");
    expect(fmtFlagValue(null)).toBe("—");
    expect(foundDate("2026-10-10T03:26:00")).toBe("2026-10-10");
  });
});

describe("noteLines", () => {
  it("is empty without flags", () => {
    expect(noteLines(undefined)).toEqual([]);
    expect(noteLines([])).toEqual([]);
  });

  it("uses each flag's plain sentence", () => {
    expect(noteLines([flag({})]).map((l) => l.text)).toEqual(["FY2026 capex is 0 in the newest row, so free cash flow may be overstated."]);
  });

  it("collapses the per-year stock-compensation flags of one ticker into one line", () => {
    const sbc = (id: number, fy: string) =>
      flag({ id, check: "sbc_gap", field: "stockBasedCompensation", fiscal_year: fy, kind: "zero_between", detail: `FY${fy} detail` });
    const lines = noteLines([sbc(2, "2024"), sbc(3, "2023")]);
    expect(lines).toHaveLength(1);
    expect(lines[0].text).toBe("Stock-based compensation reads 0 for FY2023, FY2024, so SBC totals may be understated.");
  });

  it("never shows more than three lines and says how many are left", () => {
    const many = [1, 2, 3, 4, 5].map((id) =>
      flag({ id, check: "net_income_disagreement", field: "netIncome", fiscal_year: String(2020 + id), kind: "large_gap", detail: `line ${id}` }),
    );
    const lines = noteLines(many);
    expect(lines.map((l) => l.text)).toEqual(["line 1", "line 2", "3 more in Settings > Data quality."]);
    expect(noteLines(many.slice(0, 3))).toHaveLength(3); // exactly three: no summary line
  });
});
