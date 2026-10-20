import { describe, expect, it } from "vitest";

import type { FlagLedgerRow } from "@/lib/api/types";
import { cell, group, out } from "@/lib/scorecardTestData";
import {
  cellOf,
  csvCell,
  csvFileName,
  earlyBanner,
  excessClass,
  exclusionLine,
  fmtFrac,
  fmtShare,
  groupLabel,
  ledgerCells,
  outcomesCsv,
  scorecardCsv,
  toCsv,
  weightsNote,
} from "@/lib/scorecard";

describe("formatting", () => {
  it("draws returns with an explicit sign and an em dash when missing", () => {
    expect(fmtFrac(0.041)).toBe("+4.10%");
    expect(fmtFrac(-0.008)).toBe("-0.80%");
    expect(fmtFrac(0)).toBe("0.00%");
    expect(fmtFrac(null)).toBe("—");
    expect(fmtFrac(undefined)).toBe("—");
    expect(fmtShare(0.634)).toBe("63%");
    expect(fmtShare(null)).toBe("—");
  });

  it("colours an excess only once the cell is past Early", () => {
    expect(excessClass(0.05, "too_early")).toBe("text-text-secondary");
    expect(excessClass(-0.05, "early")).toBe("text-text-secondary");
    expect(excessClass(0.05, "ok")).toMatch(/text-positive/);
    expect(excessClass(-0.05, "ok")).toMatch(/text-negative/);
    expect(excessClass(null, "ok")).toBe("text-text-tertiary");
  });

  it("lists every exclusion on the sub-line", () => {
    expect(exclusionLine({ n_pending: 2, n_censored: 1, n_entry_gap: 3, n_no_benchmark: 4, n_unpriced: 5 })).toBe(
      "2 pending · 1 censored · 3 entry gap · 4 no benchmark · 5 not priced yet",
    );
    expect(exclusionLine({ n_pending: 0, n_censored: 0, n_entry_gap: 0 })).toBe("");
  });
});

describe("labels", () => {
  it("follows the tab wording: Technical only under Reversal, Momentum-only under Momentum", () => {
    expect(groupLabel(group("a", { kind: "tier", list_name: "reversal", tier: "momentum_only" }))).toBe("Technical only");
    expect(groupLabel(group("b", { kind: "tier", list_name: "momentum", tier: "momentum_only" }))).toBe("Momentum-only");
    expect(groupLabel(group("c", { kind: "tier", list_name: "reversal", tier: "quality" }))).toBe("Quality");
    expect(groupLabel(group("d", { kind: "list", list_name: "reversal" }))).toBe("Reversal list");
    expect(groupLabel(group("e", { kind: "leveraged" }))).toBe("Leveraged ETFs");
    expect(groupLabel(group("f", { kind: "rule", rule: "B2", list_name: null }))).toBe("B2 · Price structure");
  });

  it("explains a mixed-weights cell", () => {
    expect(weightsNote(cell({ mixed_weights: true, weights_versions: [8, 9] }))).toMatch(/v8, v9/);
    expect(weightsNote(cell())).toBeNull();
  });
});

describe("earlyBanner", () => {
  it("takes every date from the response", () => {
    const text = earlyBanner(out(), 5) as string;
    expect(text).toMatch(/1 of 2 weekly lists have complete 5-session results/);
    expect(text).toMatch(/prices through 2026-10-19/);
    expect(text).toMatch(/2026-10-26 bar/);
    expect(text).toMatch(/at least 20 complete rows from at least 3 weekly lists/);
  });

  it("goes away when a list or tier cell has the cohorts for a full read", () => {
    const full = out({ groups: [group("momentum", {}, { cohorts: 8, n_complete: 80, state: "ok" })] });
    expect(earlyBanner(full, 5)).toBeNull();
  });
});

describe("csv", () => {
  it("quotes fields that need it", () => {
    expect(csvCell('a,"b"')).toBe('"a,""b"""');
    expect(csvCell(null)).toBe("");
    expect(csvCell(0.5)).toBe("0.5");
    expect(toCsv(["x", "y"], [[1, "a,b"]])).toBe('x,y\n1,"a,b"\n');
  });

  it("exports the table in long format with empty values for a gated cell", () => {
    const csv = scorecardCsv(out());
    const lines = csv.trim().split("\n");
    expect(lines[0].startsWith("group,list,tier,rule,horizon,benchmark,state,n_complete")).toBe(true);
    expect(lines).toHaveLength(1 + 4 * 2); // one group x four horizons x two benchmarks
    const first = lines[1].split(",");
    expect(first[0]).toBe("Momentum list");
    expect(first[6]).toBe("too_early");
    expect(first[14]).toBe(""); // median_excess is empty below the gate
  });

  it("exports outcome rows with their bucket", () => {
    const csv = outcomesCsv([{ source: "listed", cohort: "2026-10-09", weights_version: 8, ticker: "AAA", list_name: "momentum", tier: "quality", horizon: 5, status: "complete", censor_reason: null, bucket: "complete", rules: ["B2", "B3"] }]);
    const [header, row] = csv.trim().split("\n");
    expect(header).toContain("bucket");
    expect(row).toContain("AAA");
    expect(row).toContain("B2|B3");
  });

  it("names the files", () => {
    expect(csvFileName("table", "2026-10-19")).toBe("scorecard-table-2026-10-19.csv");
    expect(csvFileName("outcomes", null)).toBe("scorecard-outcomes.csv");
  });
});

describe("ledgerCells", () => {
  const row = (h: FlagLedgerRow["horizons"]): FlagLedgerRow => ({
    flag_id: 1, ticker: "AAA", trigger: "D3", trigger_id: "D3.pullback_to_ma.v1", list_name: "momentum", tier: "quality", leveraged: false,
    list_as_of_date: "2026-10-09", flag_date: "2026-10-12", window_open: false, already_at_ma_on_list: true, horizons: h,
  });
  const done = { status: "complete", forward_return: 0.1, excess_vs_spy: 0.09, excess_vs_sector: 0.05, stop_hit: false, stop_fill_return: null, with_stop_return: 0.1, entry_gap_flag: false };

  it("shows return, excess and the stop for a complete row", () => {
    const c = ledgerCells(row({ "5": done }), 5, "spy");
    expect(c).toMatchObject({ ret: 0.1, excess: 0.09, stop: "No stop" });
    expect(ledgerCells(row({ "5": done }), 5, "sector").excess).toBe(0.05);
  });

  it("shows the stop fill when it was hit and nothing while pending", () => {
    const stopped = { ...done, stop_hit: true, stop_fill_return: -0.1 };
    expect(ledgerCells(row({ "5": stopped }), 5, "spy").stop).toBe("Stopped -10.0%");
    const pending = { ...done, status: "pending", forward_return: null, excess_vs_spy: null, excess_vs_sector: null };
    expect(ledgerCells(row({ "5": pending }), 5, "spy")).toMatchObject({ ret: null, excess: null, stop: "—" });
    expect(ledgerCells(row({ "5": null }), 5, "spy")).toMatchObject({ ret: null, status: "not priced yet" });
  });
});

describe("cellOf", () => {
  it("reads a horizon and benchmark", () => {
    expect(cellOf(group("x", {}, { n_complete: 7 }), 10, "sector").n_complete).toBe(7);
  });
});
