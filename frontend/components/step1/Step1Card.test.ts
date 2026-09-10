import { describe, expect, it } from "vitest";

import { exemptionNote } from "@/components/step1/Step1Card";
import type { Step1Out } from "@/lib/api/types";

const TREND = { score: 75, pattern: "multiple_dips_resolved" };
const NI = { score: 75, pattern: "multiple_dips_resolved", used_operating_income_backup: false };

function makeStep1Out(overrides: Partial<Step1Out>): Step1Out {
  return {
    ticker: "TEST",
    years: ["2025", "TTM"],
    revenue: [100, 110],
    revenue_label: "Revenue",
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
