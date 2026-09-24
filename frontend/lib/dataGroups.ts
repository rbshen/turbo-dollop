import type { DataGroupOut, DataGroupState, DataGroupsOut } from "@/lib/api/types";

export const STATE_LABEL: Record<DataGroupState, string> = {
  live: "Live",
  cached_only: "Cached only",
  using_fallback: "Off — using fallback",
  not_on_plan: "Not on plan",
  restricted: "Restricted by FMP",
  failing: "Failing",
};

/** Why a group is not live, in words -- for tooltips/captions. */
export function reasonText(group: DataGroupOut): string {
  if (group.falls_back && (group.reason === "master_off" || group.reason === "user_off")) {
    return group.reason === "master_off"
      ? "The FMP master switch is off: FMP is skipped and the fallback providers (Massive, then Yahoo) serve this data."
      : "Turned off in Settings: FMP is skipped and the fallback providers (Massive, then Yahoo) serve this data.";
  }
  switch (group.reason) {
    case "master_off":
      return "The FMP master switch is off (everything is cache-only).";
    case "user_off":
      return "Turned off in Settings.";
    case "above_plan":
      return `Needs the ${group.required_tier} plan or higher.`;
    case "restricted":
      return "FMP refused this data (HTTP 402) even for a known-good symbol; re-checked weekly and when the plan is edited.";
    default:
      return "";
  }
}

/** Warning shown before turning a group off: what stops refreshing. */
export function disableWarning(group: DataGroupOut): string {
  const wired = group.wired ? group.feeds : [];
  if (group.falls_back && wired.length > 0) {
    return `Turn off ${group.label}? FMP will be skipped and the fallback providers (Massive, then Yahoo) will serve:\n\n• ${wired.join("\n• ")}`;
  }
  if (wired.length === 0) return `Turn off ${group.label}? Nothing reads it yet.`;
  return `Turn off ${group.label}? These will stop refreshing and serve cached data only:\n\n• ${wired.join("\n• ")}`;
}

/** Off groups (live features only) relevant to a page: the ones a
 * "not refreshing" badge should mention. Groups not wired yet never show. */
export function offGroupsFor(data: DataGroupsOut | undefined, keys: readonly string[]): DataGroupOut[] {
  if (!data) return [];
  return data.groups.filter((g) => g.wired && keys.includes(g.key) && g.state !== "live" && g.state !== "failing" && g.state !== "using_fallback");
}

export function asOfText(group: DataGroupOut): string {
  return group.last_success_at ? new Date(group.last_success_at).toISOString().slice(0, 10) : "last cached fetch";
}

/** Which data groups feed each ticker-page tab (only groups wired in P1 --
 * price/intraday groups arrive with P2-P5). Drives the "not refreshing"
 * badge above a tab's content. */
export const TAB_GROUPS: Record<string, readonly string[]> = {
  summary: ["profile_quote", "fundamentals", "segmentation", "news"],
  financials: ["fundamentals"],
  ratios: ["fundamentals"],
  analysis: ["fundamentals"],
  analystRatings: ["analyst_ratings"],
  valuation: ["fundamentals"],
  chart: ["corporate_events"],
};
