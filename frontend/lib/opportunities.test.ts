import { describe, expect, it } from "vitest";

import type { OpportunityRowOut, OpportunityTags } from "@/lib/api/types";
import {
  exportFileName,
  tierFilterOptions,
  tierLabel,
  exportRows,
  filterByTier,
  fmtAdvM,
  rankTitle,
  tagPills,
  thinkorswimText,
  tierCounts,
} from "@/lib/opportunities";

function row(over: Partial<OpportunityRowOut> & { tags?: OpportunityTags } = {}): OpportunityRowOut {
  return {
    ticker: "AAA",
    company_name: "AAA Inc",
    list_name: "momentum",
    tier: "quality",
    list_order: 1,
    rule_ids: ["A.momentum_trend.v1"],
    tags: {},
    overall_score: 80,
    steps_score: 80,
    overall_verdict: "Pass",
    weinstein_stage: "advance",
    vs_ma_pct: 7.5,
    ma_slope_pct: 1,
    mansfield_rs: 2,
    momentum_rank: 12,
    close: 100,
    atr: 2,
    adv_usd: 123_456_789,
    sector: "Technology",
    exchange: "NASDAQ",
    weeks_in_advance: 20,
    inputs: { momentum_group: "stocks", momentum_group_size: 569 },
    ...over,
  };
}

describe("tier filter and counts", () => {
  const rows = [row({ ticker: "Q1" }), row({ ticker: "Q2" }), row({ ticker: "M1", tier: "momentum_only" }), row({ ticker: "E1", tier: "etf" })];

  it("filters by tier and 'all' keeps everything", () => {
    expect(filterByTier(rows, "all")).toHaveLength(4);
    expect(filterByTier(rows, "quality").map((r) => r.ticker)).toEqual(["Q1", "Q2"]);
    expect(filterByTier(rows, "momentum_only").map((r) => r.ticker)).toEqual(["M1"]);
    expect(filterByTier(rows, "etf").map((r) => r.ticker)).toEqual(["E1"]);
  });

  it("counts every segment", () => {
    expect(tierCounts(rows)).toEqual({ all: 4, quality: 2, momentum_only: 1, etf: 1 });
    expect(tierCounts([])).toEqual({ all: 0, quality: 0, momentum_only: 0, etf: 0 });
  });
});

describe("tier wording per tab", () => {
  it("draws the second tier 'Technical only' on the Reversal tab and 'Momentum-only' on the Momentum tab; the stored value is unchanged", () => {
    expect(tierLabel("momentum_only", "reversal")).toBe("Technical only");
    expect(tierLabel("momentum_only", "momentum")).toBe("Momentum-only");
    for (const list of ["momentum", "reversal"] as const) {
      expect(tierLabel("quality", list)).toBe("Quality");
      expect(tierLabel("etf", list)).toBe("ETF");
    }
    // the segment value (what the filter compares) stays the stored key on both tabs
    expect(tierFilterOptions("reversal").map((o) => [o.value, o.label])).toEqual([["all", "All"], ["quality", "Quality"], ["momentum_only", "Technical only"], ["etf", "ETF"]]);
    expect(tierFilterOptions("momentum").map((o) => [o.value, o.label])).toEqual([["all", "All"], ["quality", "Quality"], ["momentum_only", "Momentum-only"], ["etf", "ETF"]]);
  });
});

describe("column formatting", () => {
  it("shows average daily dollar volume in whole millions", () => {
    expect(fmtAdvM(123_456_789)).toBe("123");
    expect(fmtAdvM(1_234_000_000)).toBe("1,234");
    expect(fmtAdvM(null)).toBe("—");
  });

  it("states the group a rank is within", () => {
    expect(rankTitle(row())).toBe("Momentum rank 12 of 569 stocks (3, 6 and 12 month composite)");
    expect(rankTitle(row({ inputs: { momentum_group: "leveraged_etfs", momentum_group_size: 3 }, momentum_rank: 1 }))).toContain("1 of 3 leveraged ETFs");
    expect(rankTitle(row({ inputs: { momentum_group: "etfs", momentum_group_size: 23 } }))).toContain("of 23 ETFs");
    expect(rankTitle(row({ momentum_rank: null }))).toBeUndefined();
  });
});

describe("tagPills", () => {
  it("is empty for a row with no stored tags", () => {
    expect(tagPills(row(), "momentum")).toEqual([]);
  });

  it("draws late trend and leveraged as warn pills", () => {
    const pills = tagPills(row({ weeks_in_advance: 60, tags: { late_trend: true, leveraged: 3 } }), "momentum");
    expect(pills.map((p) => [p.label, p.tone])).toEqual([["Late trend", "warn"], ["3x leveraged", "warn"]]);
    expect(pills[0].title).toContain("60 weeks");
  });

  it("explains why a Momentum-only stock is not Quality, in display wording ('May not pass', never 'Fail')", () => {
    const pills = tagPills(
      row({ tier: "momentum_only", overall_verdict: "Fail", tags: { why_not_quality: { overall_verdict: "Fail", failed_steps: ["Debt", "Growth rate"], incomplete_steps: [], moat: null } } }),
      "momentum",
    );
    expect(pills).toHaveLength(1);
    expect(pills[0].label).toBe("Not quality: Debt +1");
    expect(pills[0].title).toBe("Overall: May not pass · below the pass line: Debt, Growth rate · Moat not rated");
    expect(JSON.stringify(pills)).not.toMatch(/\bFail\b/);
  });

  it("on the Reversal tab the tag reads 'Fundamentals not passed' with the failed steps and moat status, in 'May not pass' wording", () => {
    const why = { overall_verdict: "Fail", failed_steps: ["Debt", "Growth rate"], incomplete_steps: [], moat: "no_moat" };
    const pill = tagPills(row({ tier: "momentum_only", tags: { why_not_quality: why } }), "reversal")[0];
    expect(pill.label).toBe("Fundamentals not passed: Debt +1");
    expect(pill.title).toBe("Overall: May not pass · below the pass line: Debt, Growth rate · No moat");
    expect(JSON.stringify(pill)).not.toMatch(/Not quality|\bFail\b/);
    const bare = tagPills(row({ tier: "momentum_only", tags: { why_not_quality: { ...why, failed_steps: [] } } }), "reversal")[0];
    expect(bare.label).toBe("Fundamentals not passed");
  });

  it("names the verdict when no step failed, and 'Incomplete' when Overall has none", () => {
    const base = { overall_verdict: "Pass with caution", failed_steps: [], incomplete_steps: [], moat: "narrow_moat" };
    expect(tagPills(row({ tier: "momentum_only", tags: { why_not_quality: base } }), "momentum")[0].label).toBe("Not quality: Pass with caution");
    const none = tagPills(row({ tier: "momentum_only", tags: { why_not_quality: { ...base, overall_verdict: null, incomplete_steps: ["Financials"] } } }), "momentum")[0];
    expect(none.label).toBe("Not quality: Incomplete");
    expect(none.title).toContain("incomplete: Financials");
  });

  it("shows held back by moat with the numbers", () => {
    const pill = tagPills(row({ steps_score: 78.4, overall_score: 55, tags: { held_back_by_moat: true } }), "momentum")[0];
    expect(pill.label).toBe("Held back by moat");
    expect(pill.title).toContain("78.4");
    expect(pill.title).toContain("55");
  });

  it("shows deep pullback with the drawdown, and has no 'also on the other list' pill (the lists are exclusive)", () => {
    const pill = tagPills(row({ inputs: { drawdown_pct: 31.4 }, tags: { deep_pullback: true } }), "momentum")[0];
    expect(pill.label).toBe("Deep pullback");
    expect(pill.title).toContain("31% below its 52-week high");
    expect(tagPills(row({ tags: { deep_pullback: true } }), "momentum")[0].title).not.toContain("NaN");
    expect(tagPills(row({ tags: {} }), "momentum").map((p) => p.label)).not.toContain("Also on reversal");
  });

  it("says 'not covered' (never 'no signal') for a ticker the signal jobs never ran for, on the Reversal tab only", () => {
    const tags: OpportunityTags = { signal_status: "not_covered" };
    expect(tagPills(row({ tags }), "reversal").map((p) => p.label)).toEqual(["Signals not covered"]);
    expect(tagPills(row({ tags }), "momentum")).toEqual([]);
    expect(tagPills(row({ tags: { signal_status: "no_signal" } }), "reversal")).toEqual([]);
    expect(tagPills(row({ tags: { signal_status: "fired" } }), "reversal")).toEqual([]);
  });

  it("summarises the sector ETF's stage and breadth", () => {
    const pills = tagPills(
      row({
        tags: {
          sector: {
            name: "Technology",
            etf: "XLK",
            stage: "advance",
            vs_ma_pct: 11.9,
            momentum_rank: 5,
            momentum_group_size: 23,
            breadth: { as_of_date: "2026-10-09", pct_above_sma50: 47, pct_above_sma200: 70, net_new_highs: 7 },
          },
        },
      }),
      "momentum",
    );
    expect(pills[0].label).toBe("XLK Advance");
    expect(pills[0].title).toBe("Technology: XLK is in Stage 2 · Advance · momentum rank 5 of 23 · 47% above 50-day · net new highs +7");
  });

  it("keeps a fixed order: late trend, leveraged, moat, why not quality, also on, coverage, sector", () => {
    const labels = tagPills(
      row({
        tags: {
          late_trend: true,
          leveraged: 3,
          held_back_by_moat: true,
          why_not_quality: { overall_verdict: "Fail", failed_steps: [], incomplete_steps: [], moat: "no_moat" },
          deep_pullback: true,
          signal_status: "not_covered",
          sector: { name: "Technology", etf: "XLK", stage: "top", vs_ma_pct: null, momentum_rank: null, momentum_group_size: null, breadth: null },
        },
      }),
      "reversal",
    ).map((p) => p.label);
    expect(labels).toEqual(["Late trend", "3x leveraged", "Held back by moat", "Fundamentals not passed", "Deep pullback", "Signals not covered", "XLK Top"]);
  });
});

describe("exports", () => {
  it("writes bare symbols one per line for thinkorswim", () => {
    expect(thinkorswimText([row({ ticker: "AAA" }), row({ ticker: "BBB" })])).toBe("AAA\nBBB\n");
    expect(thinkorswimText([])).toBe("");
  });

  it("names the files by list and date", () => {
    expect(exportFileName("momentum", "2026-10-09", "txt")).toBe("opportunities-momentum-2026-10-09.txt");
    expect(exportFileName("reversal", "2026-10-09", "csv")).toBe("opportunities-reversal-2026-10-09_thinkorswim.csv");
  });

  it("gives an ETF no sector, so TradingView groups it under Other", () => {
    expect(exportRows([row({ ticker: "AAA" }), row({ ticker: "ETF1", tier: "etf", sector: "Technology", exchange: "AMEX" })])).toEqual([
      { ticker: "AAA", exchange: "NASDAQ", sector: "Technology" },
      { ticker: "ETF1", exchange: "AMEX", sector: null },
    ]);
  });
});
