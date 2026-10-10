import { describe, expect, it } from "vitest";

import { DEFAULT_ETF_TICKER_TAB, DEFAULT_TICKER_TAB, ETF_TICKER_TABS, TICKER_TABS } from "@/lib/tickerTabs";

describe("tickerTabs", () => {
  it("has exactly the 10 tabs, in display order", () => {
    expect(TICKER_TABS.map((t) => t.key)).toEqual([
      "summary",
      "dashboard",
      "financials",
      "ratios",
      "analysis",
      "valuation",
      "moat",
      "analystRatings",
      "technical",
      "chart",
    ]);
  });

  it("does not expose the shelved Institutional Ownership tab", () => {
    expect(TICKER_TABS.map((t) => t.key)).not.toContain("institutionalOwnership");
    expect(TICKER_TABS.map((t) => t.label)).not.toContain("Institutional Ownership");
  });

  it("every tab has a unique key", () => {
    const keys = TICKER_TABS.map((t) => t.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("every tab has a non-empty label", () => {
    for (const tab of TICKER_TABS) {
      expect(tab.label.length).toBeGreaterThan(0);
    }
  });

  it("puts Dashboard second, after Summary, labelled 'Dashboard' (the key 'overview' is the ETF page's)", () => {
    expect(TICKER_TABS[1]).toEqual({ key: "dashboard", label: "Dashboard" });
    expect(TICKER_TABS.map((t) => t.key)).not.toContain("overview");
  });

  it("defaults to the Summary tab", () => {
    expect(DEFAULT_TICKER_TAB).toBe("summary");
    expect(TICKER_TABS.some((t) => t.key === DEFAULT_TICKER_TAB)).toBe(true);
  });

  it("the ETF variant has exactly Overview, Technical, Chart (no stock-only tab), defaulting to Overview", () => {
    expect(ETF_TICKER_TABS.map((t) => t.label)).toEqual(["Overview", "Technical", "Chart"]);
    expect(DEFAULT_ETF_TICKER_TAB).toBe("overview");
    // The stock page's tab set is untouched by the ETF branch.
    expect(TICKER_TABS.map((t) => t.key)).not.toContain("overview");
    for (const stockOnly of ["dashboard", "financials", "ratios", "analysis", "valuation", "moat", "analystRatings"]) {
      expect(ETF_TICKER_TABS.map((t) => t.key)).not.toContain(stockOnly);
    }
  });
});
