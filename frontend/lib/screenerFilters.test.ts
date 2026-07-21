import { describe, expect, it } from "vitest";

import type { TickerScoreOut } from "@/lib/api/types";
import {
  DEFAULT_FILTER_STATE,
  extractCompanyTypes,
  extractSectors,
  filterTickerScores,
  sortTickerScores,
  type ScreenerFilterState,
} from "@/lib/screenerFilters";

function row(overrides: Partial<TickerScoreOut> = {}): TickerScoreOut {
  return {
    ticker: "AAPL",
    company_name: "Apple Inc.",
    sector: "Technology",
    industry: "Consumer Electronics",
    company_type: "Standard",
    step1_score: 90,
    step1_verdict: "Strong Pass",
    step2_score: 80,
    step2_verdict: "Pass",
    step4_score: 70,
    step4_verdict: "Pass",
    step5_score: 60,
    step5_verdict: "Pass",
    overall_score: 78,
    overall_verdict: "Pass",
    market_cap: 3_000_000_000_000,
    pe_ratio: 30,
    beta: 1.2,
    computed_at: "2026-01-01T00:00:00",
    ...overrides,
  };
}

describe("filterTickerScores", () => {
  it("returns everything unfiltered when every field is at its default (no-op)", () => {
    const rows = [row({ ticker: "AAPL" }), row({ ticker: "MSFT" })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(2);
  });

  it("filters by an Overall score range", () => {
    const rows = [row({ ticker: "HIGH", overall_score: 90 }), row({ ticker: "LOW", overall_score: 20 })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, overallScore: { min: 70, max: null } };
    const result = filterTickerScores(rows, filters);
    expect(result.map((r) => r.ticker)).toEqual(["HIGH"]);
  });

  it("excludes an Incomplete ticker (null overall_score) when an Overall range filter is active", () => {
    // The exact case the spec calls out: filtering "Overall score > 70"
    // must never treat a missing score as passing.
    const rows = [row({ ticker: "SCORED", overall_score: 90 }), row({ ticker: "INCOMPLETE", overall_score: null })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, overallScore: { min: 70, max: null } };
    const result = filterTickerScores(rows, filters);
    expect(result.map((r) => r.ticker)).toEqual(["SCORED"]);
  });

  it("does not exclude an Incomplete ticker when no filter is active on its missing field", () => {
    const rows = [row({ ticker: "INCOMPLETE", overall_score: null })];
    expect(filterTickerScores(rows, DEFAULT_FILTER_STATE)).toHaveLength(1);
  });

  it("filters by a min/max range together", () => {
    const rows = [row({ ticker: "A", pe_ratio: 5 }), row({ ticker: "B", pe_ratio: 20 }), row({ ticker: "C", pe_ratio: 50 })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, peRatio: { min: 10, max: 30 } };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["B"]);
  });

  it("filters by sector multi-select", () => {
    const rows = [
      row({ ticker: "TECH", sector: "Technology" }),
      row({ ticker: "FIN", sector: "Financial Services" }),
      row({ ticker: "HEALTH", sector: "Healthcare" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, sectors: ["Technology", "Healthcare"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["TECH", "HEALTH"]);
  });

  it("filters by company type multi-select", () => {
    const rows = [
      row({ ticker: "BANK1", company_type: "Bank" }),
      row({ ticker: "STD1", company_type: "Standard" }),
      row({ ticker: "BANK2", company_type: "Bank" }),
    ];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, companyTypes: ["Bank"] };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["BANK1", "BANK2"]);
  });

  it("combines a score filter and a company type filter (AND, not OR)", () => {
    const rows = [
      row({ ticker: "BANK_HIGH", company_type: "Bank", step5_score: 90 }),
      row({ ticker: "BANK_LOW", company_type: "Bank", step5_score: 10 }),
      row({ ticker: "STD_HIGH", company_type: "Standard", step5_score: 90 }),
    ];
    const filters: ScreenerFilterState = {
      ...DEFAULT_FILTER_STATE,
      companyTypes: ["Bank"],
      step5Score: { min: 70, max: null },
    };
    expect(filterTickerScores(rows, filters).map((r) => r.ticker)).toEqual(["BANK_HIGH"]);
  });

  it("excludes a ticker missing sector entirely once a sector filter is active", () => {
    const rows = [row({ ticker: "NOSECTOR", sector: null })];
    const filters: ScreenerFilterState = { ...DEFAULT_FILTER_STATE, sectors: ["Technology"] };
    expect(filterTickerScores(rows, filters)).toHaveLength(0);
  });
});

describe("sortTickerScores", () => {
  it("sorts ascending by a score field", () => {
    const rows = [row({ ticker: "B", step5_score: 50 }), row({ ticker: "A", step5_score: 10 }), row({ ticker: "C", step5_score: 90 })];
    expect(sortTickerScores(rows, "step5_score", "asc").map((r) => r.ticker)).toEqual(["A", "B", "C"]);
  });

  it("sorts descending by a score field", () => {
    const rows = [row({ ticker: "B", step5_score: 50 }), row({ ticker: "A", step5_score: 10 }), row({ ticker: "C", step5_score: 90 })];
    expect(sortTickerScores(rows, "step5_score", "desc").map((r) => r.ticker)).toEqual(["C", "B", "A"]);
  });

  it("sorts nulls to the end regardless of direction (ascending)", () => {
    const rows = [
      row({ ticker: "MID", step5_score: 50 }),
      row({ ticker: "NULL", step5_score: null }),
      row({ ticker: "LOW", step5_score: 10 }),
    ];
    expect(sortTickerScores(rows, "step5_score", "asc").map((r) => r.ticker)).toEqual(["LOW", "MID", "NULL"]);
  });

  it("sorts nulls to the end regardless of direction (descending)", () => {
    const rows = [
      row({ ticker: "MID", step5_score: 50 }),
      row({ ticker: "NULL", step5_score: null }),
      row({ ticker: "LOW", step5_score: 10 }),
    ];
    expect(sortTickerScores(rows, "step5_score", "desc").map((r) => r.ticker)).toEqual(["MID", "LOW", "NULL"]);
  });

  it("does not mutate the input array", () => {
    const rows = [row({ ticker: "B", step5_score: 50 }), row({ ticker: "A", step5_score: 10 })];
    const original = [...rows];
    sortTickerScores(rows, "step5_score", "asc");
    expect(rows).toEqual(original);
  });

  it("sorts by a raw metric field (market cap)", () => {
    const rows = [
      row({ ticker: "SMALL", market_cap: 1_000_000_000 }),
      row({ ticker: "BIG", market_cap: 3_000_000_000_000 }),
    ];
    expect(sortTickerScores(rows, "market_cap", "desc").map((r) => r.ticker)).toEqual(["BIG", "SMALL"]);
  });
});

describe("extractSectors / extractCompanyTypes", () => {
  it("extracts unique, sorted, non-null sector values", () => {
    const rows = [row({ sector: "Technology" }), row({ sector: "Healthcare" }), row({ sector: "Technology" }), row({ sector: null })];
    expect(extractSectors(rows)).toEqual(["Healthcare", "Technology"]);
  });

  it("extracts unique, sorted, non-null company type values", () => {
    const rows = [row({ company_type: "Bank" }), row({ company_type: "Standard" }), row({ company_type: "Bank" })];
    expect(extractCompanyTypes(rows)).toEqual(["Bank", "Standard"]);
  });
});
