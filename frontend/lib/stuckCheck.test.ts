import { describe, expect, it } from "vitest";

import type { StuckFigure, StuckRow } from "@/lib/api/types";
import { collapseNotes, formatFigure, gaugeCaption, isShownRow, STATUS_LABEL } from "@/lib/stuckCheck";

const fig = (over: Partial<StuckFigure>): StuckFigure => ({ key: "k", label: "L", value: null, unit: "pct", text: null, ...over });

describe("formatFigure", () => {
  it.each([
    [{ unit: "pct", value: 22.14 }, "22.1%"],
    [{ unit: "pct", value: -3.06 }, "-3.1%"],
    [{ unit: "pp", value: 1.34 }, "+1.3%"],
    [{ unit: "pp", value: -36.5 }, "−36.5%"],
    [{ unit: "pp", value: 0 }, "0.0%"],
    [{ unit: "ratio", value: 0.66 }, "0.66"],
    [{ unit: "multiple", value: 2.5 }, "2.5×"],
    [{ unit: "money", value: 1_096_679_000 }, "$1.10B"],
    [{ unit: "money", value: -56_708_000_000 }, "-$56.71B"],
    [{ unit: "money", value: 5_000 }, "$5,000.00"],
  ])("formats %o as %s", (over, expected) => {
    expect(formatFigure(fig(over))).toBe(expected);
  });

  it("uses the reporting currency for money", () => {
    expect(formatFigure(fig({ unit: "money", value: 2_000_000_000 }), "CNY")).toMatch(/2\.00B$/);
    expect(formatFigure(fig({ unit: "money", value: 2_000_000_000 }), "CNY")).not.toMatch(/^\$/);
  });

  it("shows the word alone when there is no value, and beside the figure when there is one", () => {
    expect(formatFigure(fig({ value: null, text: "n/m" }))).toBe("n/m");
    expect(formatFigure(fig({ value: null, text: null }))).toBe("—");
    expect(formatFigure(fig({ unit: "pp", value: 107.07, text: "leads" }))).toBe("+107.1% · leads");
    expect(formatFigure(fig({ unit: "text", value: null, text: "No buybacks" }))).toBe("No buybacks");
    expect(formatFigure(fig({ unit: "count", value: 93, text: "93rd percentile" }))).toBe("93rd percentile");
  });
});

const row = (over: Partial<StuckRow> & Pick<StuckRow, "title">): StuckRow =>
  ({ key: over.title, number: 1, status: null, reason: null, figures: [], notes: [], ...over }) as StuckRow;

describe("labels", () => {
  it("has exactly the four labels, none of them a verdict word, and 'Not flagged' replaces 'OK'", () => {
    expect(Object.values(STATUS_LABEL)).toEqual(["Not flagged", "Flagged", "Not applicable", "Not reported"]);
    expect(Object.values(STATUS_LABEL)).not.toContain("OK");
  });
});

describe("collapseNotes", () => {
  it("isShownRow hides only Not applicable and Not reported rows", () => {
    expect(["not_flagged", "flagged", null].map((status) => isShownRow(row({ title: "x", status: status as StuckRow["status"] })))).toEqual([true, true, true]);
    expect(["not_applicable", "not_reported"].map((status) => isShownRow(row({ title: "x", status: status as StuckRow["status"] })))).toEqual([false, false]);
  });

  it("merges rows with the same reason into one sentence and keeps distinct reasons separate", () => {
    const notes = collapseNotes([
      row({ title: "Cash conversion", status: "not_applicable", reason: "Free cash flow is not comparable for a bank" }),
      row({ title: "FCF after stock-based compensation", status: "not_applicable", reason: "Free cash flow is not comparable for a bank" }),
      row({ title: "Share count", status: "not_applicable", reason: "Fewer than 3 fiscal years since the listing" }),
    ]);
    expect(notes).toEqual([
      "Cash conversion and FCF after stock-based compensation: Free cash flow is not comparable for a bank.",
      "Share count: Fewer than 3 fiscal years since the listing.",
    ]);
  });

  it("names three rows with a comma list, includes row notes, and drops a row that is shown from the reasons", () => {
    const notes = collapseNotes([
      row({ title: "A", status: "not_reported", reason: "Cash flow is missing" }),
      row({ title: "B", status: "not_reported", reason: "Cash flow is missing" }),
      row({ title: "Cash flow row", status: "not_reported", reason: "Cash flow is missing" }),
      row({ title: "Shown", status: "not_flagged", reason: "ignored", notes: ["Only 2 fiscal years since the listing: latest year shown, no label"] }),
    ]);
    expect(notes).toEqual(["A, B and cash flow row: Cash flow is missing.", "Only 2 fiscal years since the listing: latest year shown, no label."]);
  });

  it("returns nothing when there is nothing to say", () => {
    expect(collapseNotes([row({ title: "x", status: "flagged" })])).toEqual([]);
  });
});

describe("gaugeCaption", () => {
  it("says where the row flags", () => {
    const pct = (n: number) => `${n}%`;
    expect(gaugeCaption("ceiling", 8, pct)).toBe("Flagged above 8%");
    expect(gaugeCaption("floor", 0.7, (n) => n.toFixed(2))).toBe("Flagged below 0.70");
    expect(gaugeCaption("floor", 0, pct)).toBe("Flagged at zero or below");
  });
});
