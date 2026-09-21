import { describe, expect, it } from "vitest";

import type { MarketBreadthPointOut } from "@/lib/api/types";
import { firstLiveIndex, fmtAxisMonth, fmtBreadthPct, fmtSignedCount } from "@/lib/marketBreadth";

const point = (as_of_date: string, is_backfilled: boolean): MarketBreadthPointOut => ({
  as_of_date, pct_above_sma50: 50, pct_above_sma200: 50, sma50_above: 1, sma200_above: 1, new_highs: 0, new_lows: 0,
  net_new_highs: 0, constituents: 2, stale_excluded: 0, sma50_eligible: 2, sma200_eligible: 2, hl_eligible: 2, is_backfilled,
});

describe("firstLiveIndex", () => {
  it("finds the boundary between the backfilled past and live rows", () => {
    expect(firstLiveIndex([point("2026-09-16", true), point("2026-09-17", true), point("2026-09-18", false), point("2026-09-19", false)])).toBe(2);
  });
  it("is -1 when every session is backfilled, and 0 when none is", () => {
    expect(firstLiveIndex([point("2026-09-17", true), point("2026-09-18", true)])).toBe(-1);
    expect(firstLiveIndex([point("2026-09-17", false)])).toBe(0);
    expect(firstLiveIndex([])).toBe(-1);
  });
});

describe("formatters", () => {
  it("signs counts", () => {
    expect(fmtSignedCount(78)).toBe("+78");
    expect(fmtSignedCount(-24)).toBe("-24");
    expect(fmtSignedCount(0)).toBe("0");
  });
  it("formats percentages and a missing one", () => {
    expect(fmtBreadthPct(27.833)).toBe("27.8%");
    expect(fmtBreadthPct(null)).toBe("—");
  });
  it("labels an axis month timezone-safely", () => {
    expect(fmtAxisMonth("2026-09-01")).toBe("Sep '26");
    expect(fmtAxisMonth("2026-12-31")).toBe("Dec '26");
    expect(fmtAxisMonth("garbage")).toBe("garbage");
  });
});
