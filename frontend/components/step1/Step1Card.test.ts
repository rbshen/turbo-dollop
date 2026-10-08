import { describe, expect, it } from "vitest";

import { backupNote, exemptionNote, TIER_LABELS } from "@/components/step1/Step1Card";
import type { Step1Out } from "@/lib/api/types";

const TREND = { score: 75, pattern: "uptrend_dips" };
const NI = { score: 75, pattern: "uptrend_dips", used_operating_income_backup: false };

function makeStep1Out(overrides: Partial<Step1Out>): Step1Out {
  return {
    ticker: "TEST",
    years: ["2025", "TTM"],
    revenue: [100, 110],
    net_income: [10, 11],
    operating_income: [10, 11],
    cfo: null,
    fcf: null,
    gross_margin: [40, 41],
    net_margin: [10, 11],
    cfo_exempt_reason: null,
    net_income_one_off: false,
    cfo_one_off: false,
    score: 80,
    verdict: "Pass",
    components: {
      revenue: TREND,
      net_income: NI,
      cfo: null,
      margins: null,
      fcf: null,
    },
    weights: { revenue: 1, net_income: 0, cfo: 0, margins: 0, fcf: 0 },
    ...overrides,
  };
}

describe("exemptionNote", () => {
  it("returns null for a non-exempt (Standard) company", () => {
    const data = makeStep1Out({
      cfo_exempt_reason: null,
      components: { revenue: TREND, net_income: NI, cfo: TREND, margins: TREND, fcf: TREND },
    });
    expect(exemptionNote(data)).toBeNull();
  });

  it("names Cash Flow and Free Cash Flow for a non-Bank exempt type (Margins still scored)", () => {
    const data = makeStep1Out({
      cfo_exempt_reason: "Insurance",
      components: { revenue: TREND, net_income: NI, cfo: null, margins: TREND, fcf: null },
    });
    expect(exemptionNote(data)).toBe(
      "Cash Flow and Free Cash Flow aren't scored for this company — classified as a Insurance.",
    );
  });

  it("also names Margins for a Bank (all three excluded)", () => {
    const data = makeStep1Out({
      cfo_exempt_reason: "Bank",
      components: { revenue: TREND, net_income: NI, cfo: null, margins: null, fcf: null },
    });
    expect(exemptionNote(data)).toBe(
      "Cash Flow, Margins, and Free Cash Flow aren't scored for this company — classified as a Bank.",
    );
  });

  it("uses singular 'isn't' when only one metric is excluded", () => {
    // Not a real production shape (Margins-only exemption never happens
    // without CFO/FCF too), but exercises the singular/plural branch
    // directly regardless.
    const data = makeStep1Out({
      cfo_exempt_reason: "Bank",
      components: { revenue: TREND, net_income: NI, cfo: TREND, margins: null, fcf: TREND },
    });
    expect(exemptionNote(data)).toBe("Margins isn't scored for this company — classified as a Bank.");
  });

  it("returns null if cfo_exempt_reason is set but nothing is actually excluded", () => {
    const data = makeStep1Out({
      cfo_exempt_reason: "Commodity Company",
      components: { revenue: TREND, net_income: NI, cfo: TREND, margins: TREND, fcf: TREND },
    });
    expect(exemptionNote(data)).toBeNull();
  });
});

// Every pattern scoring/step1.py can emit: the engine's six labels, the positivity gate and insufficient_data.
const BACKEND_PATTERNS = [
  "insufficient_data",
  "not_yet_positive",
  "uptrend",
  "uptrend_dips",
  "flat",
  "flat_dips",
  "decline",
  "decline_dips",
];

describe("TIER_LABELS", () => {
  it("has a readable label for every pattern the backend can emit", () => {
    for (const pattern of BACKEND_PATTERNS) {
      expect(TIER_LABELS[pattern], pattern).toBeTruthy();
      expect(TIER_LABELS[pattern], pattern).not.toBe(pattern);
    }
  });

  it("labels not_yet_positive", () => {
    expect(TIER_LABELS.not_yet_positive).toBe("Not yet positive");
  });
});

const LIFTED_NI = {
  score: 80,
  pattern: "flat_dips",
  used_operating_income_backup: true,
  score_before_backup: 65,
  backup_gates: { oi_margin_pct: 7.3, min_oi_margin_pct: 5, positive_periods: 4, min_positive_periods: 4, window: 5 },
};

describe("backupNote", () => {
  it("is null when the backup did not change the score", () => {
    expect(backupNote(makeStep1Out({}))).toBeNull();
  });

  it("is shown with the tooltip's before/after score and both gate values when the flag is true", () => {
    const note = backupNote(
      makeStep1Out({ components: { revenue: TREND, net_income: LIFTED_NI, cfo: null, margins: null, fcf: null } }),
    );
    expect(note?.text).toBe("Score lifted using Operating Income (backup)");
    expect(note?.tooltip).toBe(
      "Net Income was inconsistent, which can be distorted by one-offs, so the score uses Operating Income, which strips them out. " +
        "Net Income score 65 lifted to 80. Backup gates: last fiscal year Operating Income margin 7.3% (needs at least 5%), " +
        "positive in 4 of the last 5 fiscal years (needs at least 4).",
    );
  });

  it("reads only the Net Income component: another component's fields never trigger it", () => {
    const data = makeStep1Out({
      components: { revenue: { ...TREND, used_operating_income_backup: true } as typeof TREND, net_income: NI, cfo: TREND, margins: TREND, fcf: TREND },
    });
    expect(backupNote(data)).toBeNull();
  });
});
