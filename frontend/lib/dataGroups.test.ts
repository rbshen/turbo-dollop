import { describe, expect, it } from "vitest";

import type { DataGroupOut, DataGroupsOut } from "@/lib/api/types";
import { TAB_GROUPS, asOfText, disableWarning, offGroupsFor, reasonText } from "@/lib/dataGroups";

function group(over: Partial<DataGroupOut> = {}): DataGroupOut {
  return {
    key: "news",
    label: "News",
    wired: true,
    enabled: true,
    state: "live",
    reason: "live",
    required_tier: "Starter",
    tier_verified: false,
    restricted_since: null,
    last_success_at: null,
    last_error: null,
    feeds: ["News tab"],
    can_toggle: true,
    ...over,
  };
}

const wrap = (groups: DataGroupOut[]): DataGroupsOut => ({
  master_on: true,
  fmp_plan: "Ultimate",
  tiers: ["Starter", "Premium", "Ultimate"],
  key_problem_at: null,
  key_problem_detail: null,
  groups,
});

describe("offGroupsFor", () => {
  it("returns nothing while loading or when every group is live/failing", () => {
    expect(offGroupsFor(undefined, ["news"])).toEqual([]);
    expect(offGroupsFor(wrap([group()]), ["news"])).toEqual([]);
    expect(offGroupsFor(wrap([group({ state: "failing" })]), ["news"])).toEqual([]);
  });

  it("returns off groups that feed the page, ignoring unrelated and not-wired ones", () => {
    const data = wrap([
      group({ key: "news", state: "cached_only", reason: "user_off" }),
      group({ key: "segmentation", label: "Segmentation", state: "restricted", reason: "restricted" }),
      group({ key: "daily_prices", label: "Daily prices", wired: false, state: "cached_only", reason: "user_off" }),
    ]);
    expect(offGroupsFor(data, ["news", "daily_prices"]).map((g) => g.key)).toEqual(["news"]);
  });
});

describe("fallback groups", () => {
  it("do not read as not-refreshing when off, and word the reason/warning around the fallback", () => {
    const g = group({ key: "daily_prices", falls_back: true, state: "using_fallback", reason: "user_off" });
    expect(offGroupsFor(wrap([g]), ["daily_prices"])).toEqual([]);
    expect(reasonText(g)).toContain("fallback");
    expect(disableWarning(g)).toContain("Massive");
    expect(disableWarning(g)).not.toContain("cached data only");
  });
});

describe("text helpers", () => {
  it("asOfText uses the last success date, else a fallback", () => {
    expect(asOfText(group({ last_success_at: "2026-09-20T03:00:00" }))).toBe("2026-09-20");
    expect(asOfText(group())).toBe("last cached fetch");
  });

  it("disableWarning lists dependent features, and says so when nothing reads the group", () => {
    expect(disableWarning(group({ feeds: ["News tab", "Digest"] }))).toContain("• News tab\n• Digest");
    expect(disableWarning(group({ wired: false }))).toContain("Nothing reads it yet");
  });

  it("reasonText names the plan for above_plan", () => {
    expect(reasonText(group({ reason: "above_plan", required_tier: "Ultimate" }))).toContain("Ultimate");
    expect(reasonText(group())).toBe("");
  });

  it("TAB_GROUPS only references real tabs' fundamentals-era groups", () => {
    expect(TAB_GROUPS.analystRatings).toEqual(["analyst_ratings"]);
  });
});
