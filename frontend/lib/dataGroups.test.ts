import { describe, expect, it } from "vitest";

import type { DataGroupOut, DataGroupsOut } from "@/lib/api/types";
import { TAB_GROUPS, asOfText, disableWarning, offGroupsFor, reasonText, unavailableNote } from "@/lib/dataGroups";

function group(over: Partial<DataGroupOut> = {}): DataGroupOut {
  return {
    key: "news",
    label: "News",
    wired: true,
    enabled: true,
    state: "live",
    reason: "live",
    required_tier: "Starter",
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

describe("price groups (no fallback provider)", () => {
  it("read as cached-only when off, with the plain cached-data wording", () => {
    for (const key of ["daily_prices", "intraday_bars", "daily_prices_long"]) {
      const off = group({ key, state: "cached_only", reason: "user_off", feeds: ["Chart tab"] });
      expect(offGroupsFor(wrap([off]), [key]).map((g) => g.key)).toEqual([key]);
      expect(reasonText(off)).toBe("Turned off in Settings.");
      expect(disableWarning(off)).toContain("serve cached data only");
      expect(reasonText(off)).not.toContain("fallback");
    }
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

  it("TAB_GROUPS maps each tab to the data groups that feed it", () => {
    expect(TAB_GROUPS.analystRatings).toEqual(["analyst_ratings", "daily_prices_long"]);
    // Price groups have no fallback provider: an off one is what explains a stale/empty Chart or Technical tab.
    expect(TAB_GROUPS.chart).toEqual(expect.arrayContaining(["daily_prices", "daily_prices_long", "intraday_bars"]));
    expect(TAB_GROUPS.technical).toEqual(["daily_prices", "intraday_bars"]);
    // The Dashboard draws cached statements, the quote and daily bars.
    expect(TAB_GROUPS.dashboard).toEqual(["profile_quote", "fundamentals", "daily_prices"]);
  });

  it("never watches `news` -- shelved, not broken, must never trigger the badge", () => {
    for (const groups of Object.values(TAB_GROUPS)) {
      expect(groups).not.toContain("news");
    }
  });
});

describe("ETF overview tab", () => {
  it("is fed by the etf_info group, so a paused group shows the not-refreshing badge on it", () => {
    expect(TAB_GROUPS.overview).toEqual(["etf_info"]);
    const data = wrap([group({ key: "etf_info", label: "ETF info", state: "cached_only", reason: "user_off" })]);
    expect(offGroupsFor(data, TAB_GROUPS.overview).map((g) => g.key)).toEqual(["etf_info"]);
  });
});

describe("unavailableNote", () => {
  const variant = (label: string) => ({ key: label, label, restricted_since: "2026-10-02T03:00:00Z", last_error: null, last_probe_at: null });

  it("is null when nothing is refused", () => {
    expect(unavailableNote(group())).toBeNull();
    expect(unavailableNote(group({ unavailable_variants: [] }))).toBeNull();
  });

  it("names quarterly data compactly, dropping the limit suffix", () => {
    const g = group({ unavailable_variants: [variant("Quarterly income statement (limit 12)"), variant("Quarterly balance sheet (limit 12)")] });
    expect(unavailableNote(g)).toBe("Quarterly data not on plan: income statement, balance sheet");
  });

  it("lists any other refused variant as is", () => {
    const g = group({ unavailable_variants: [variant("Annual income statement (limit 10)")] });
    expect(unavailableNote(g)).toBe("Not on plan: Annual income statement");
  });
});
