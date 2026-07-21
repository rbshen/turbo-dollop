import { describe, expect, it } from "vitest";

import { DEFAULT_TICKER_TAB, TICKER_TABS } from "@/lib/tickerTabs";

describe("tickerTabs", () => {
  it("has exactly the 5 Phase A tabs, in display order", () => {
    expect(TICKER_TABS.map((t) => t.key)).toEqual([
      "summary",
      "financials",
      "companyMetrics",
      "analysis",
      "valuation",
    ]);
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

  it("defaults to the Summary tab", () => {
    expect(DEFAULT_TICKER_TAB).toBe("summary");
    expect(TICKER_TABS.some((t) => t.key === DEFAULT_TICKER_TAB)).toBe(true);
  });
});
