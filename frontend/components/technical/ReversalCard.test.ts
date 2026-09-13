import { describe, expect, it } from "vitest";

import { reversalDisplayStatus, reversalFreshnessCaption, reversalStatus } from "@/components/technical/ReversalCard";
import type { TrendAnalysisOut } from "@/lib/api/types";

// Only last_confirmed_swing/magnitude_tier/ad_bullish_divergence/
// bars_since_confirmation vary across the cases below -- every other field
// is irrelevant to reversalStatus/reversalDisplayStatus, so a single base
// object (a confirmed-and-current reversal, matching VZ's real shape from
// the investigation this feature shipped under) keeps each test focused on
// what actually matters.
function trendAnalysis(overrides: Partial<TrendAnalysisOut>): TrendAnalysisOut {
  return {
    ticker: "VZ",
    computed_at: "2026-09-07T00:00:00Z",
    trend_state: "downtrend",
    magnitude_tier: "strong",
    persistence_count: 1,
    bars_since_confirmation: 10,
    last_confirmed_swing: { date: "2026-07-01", price: 41.29, margin: 2.83, atr: 1.32, ratio: 2.14, classification: "LL" },
    warning_flag: false,
    warning_swing: null,
    pullback_occurred_since_flip: false,
    trend_started: null,
    trend_started_is_lower_bound: null,
    efficiency_ratio: null,
    regime: null,
    blended_score: -3.71,
    bar_level: 2,
    ad_bullish_divergence: true,
    ad_divergence_swing_date: "2026-06-22",
    sma20_position_pct: null,
    sma20_cross: null,
    sma50_position_pct: null,
    sma50_cross: null,
    sma200_position_pct: null,
    sma200_cross: null,
    weinstein_stage: null,
    weinstein_stage_since_date: null,
    weinstein_stage_since_is_lower_bound: null,
    weinstein_weeks_available: null,
    weinstein_stage_changed: null,
    weinstein_ma_slope_pct: null,
    weinstein_vs_ma_pct: null,
    weinstein_volume_ratio: null,
    weinstein_mansfield_rs: null,
    weinstein_breakout_confirmed: null,
    ...overrides,
  };
}

describe("reversalDisplayStatus", () => {
  it("reads as Confirmed (not stale) when the confirming low is fresh, under the 21-bar window", () => {
    const data = trendAnalysis({ bars_since_confirmation: 10 });
    expect(reversalStatus(data)).toBe("Confirmed");
    expect(reversalDisplayStatus(data)).toBe("Confirmed");
  });

  it("still reads as plain Confirmed (not yet stale) once aged past the 21-bar edge window but under the 42-bar stale threshold", () => {
    // Mirrors what VZ's OWN reading would be under a 63-bar stale threshold --
    // deliberately not what's used here (42 bars), so this case picks a value
    // just past 21 and clearly under 42.
    const data = trendAnalysis({ bars_since_confirmation: 30 });
    expect(reversalStatus(data)).toBe("Confirmed");
    expect(reversalDisplayStatus(data)).toBe("Confirmed");
  });

  it("downgrades to Confirmed (stale) at exactly the 42-bar threshold", () => {
    const data = trendAnalysis({ bars_since_confirmation: 42 });
    expect(reversalDisplayStatus(data)).toBe("Confirmed (stale)");
  });

  it("downgrades to Confirmed (stale) past 42 bars -- VZ's real 46-bar reading from the investigation lands here", () => {
    const data = trendAnalysis({ bars_since_confirmation: 46 });
    expect(reversalStatus(data)).toBe("Confirmed");
    expect(reversalDisplayStatus(data)).toBe("Confirmed (stale)");
  });

  it("reads as Not present when there's no current reversal signal at all, regardless of bars_since_confirmation", () => {
    const data = trendAnalysis({ last_confirmed_swing: null, ad_bullish_divergence: false, bars_since_confirmation: 100 });
    expect(reversalStatus(data)).toBe("Not present");
    expect(reversalDisplayStatus(data)).toBe("Not present");
  });

  it("treats a null bars_since_confirmation as not-stale (fails open, matching every other nullable field on this type)", () => {
    const data = trendAnalysis({ bars_since_confirmation: null });
    expect(reversalDisplayStatus(data)).toBe("Confirmed");
  });
});

describe("reversalFreshnessCaption", () => {
  it("reads as the illustrative-window caption while still inside the 21-bar edge window", () => {
    expect(reversalFreshnessCaption(10)).toMatch(/21-trading-day/);
    expect(reversalFreshnessCaption(20)).toMatch(/21-trading-day/);
  });

  it("reads as the aged (not yet stale) caption between 21 and 42 bars", () => {
    expect(reversalFreshnessCaption(21)).toMatch(/still within reporting range/);
    expect(reversalFreshnessCaption(41)).toMatch(/still within reporting range/);
  });

  it("reads as the stale caption at and past 42 bars", () => {
    expect(reversalFreshnessCaption(42)).toMatch(/flagged stale/);
    expect(reversalFreshnessCaption(46)).toMatch(/flagged stale/);
  });

  it("treats a null bars_since_confirmation the same as fresh", () => {
    expect(reversalFreshnessCaption(null)).toMatch(/21-trading-day/);
  });
});
