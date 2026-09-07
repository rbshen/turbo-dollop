import { describe, expect, it } from "vitest";

import { FRESHNESS_LABEL, invalidatedFreshnessText, resolutionStatus } from "@/components/technical/TrendContinuationCard";
import type { TrendAnalysisOut } from "@/lib/api/types";

// Only trend_state/warning_flag/pullback_occurred_since_flip vary across the
// cases below -- every other field is irrelevant to resolutionStatus, so a
// single base object keeps each test focused on what actually matters.
function trendAnalysis(overrides: Partial<TrendAnalysisOut>): TrendAnalysisOut {
  return {
    ticker: "AAPL",
    computed_at: "2026-09-07T00:00:00Z",
    trend_state: "uptrend",
    magnitude_tier: "strong",
    persistence_count: 3,
    bars_since_confirmation: 5,
    last_confirmed_swing: null,
    warning_flag: false,
    warning_swing: null,
    pullback_occurred_since_flip: false,
    efficiency_ratio: null,
    regime: null,
    blended_score: 5,
    bar_level: 4,
    ad_bullish_divergence: false,
    ad_divergence_swing_date: null,
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

describe("resolutionStatus", () => {
  it("reads as NoPullback when no pullback has occurred since the last flip", () => {
    const data = trendAnalysis({ trend_state: "uptrend", warning_flag: false, pullback_occurred_since_flip: false });
    expect(resolutionStatus(data)).toBe("NoPullback");
  });

  it("reads as NoPullback (not Recovered) for a legacy row with a null pullback_occurred_since_flip", () => {
    const data = trendAnalysis({ trend_state: "uptrend", warning_flag: false, pullback_occurred_since_flip: null });
    expect(resolutionStatus(data)).toBe("NoPullback");
  });

  it("reads as Pending while a pullback warning is currently active", () => {
    const data = trendAnalysis({ trend_state: "uptrend", warning_flag: true, pullback_occurred_since_flip: true });
    expect(resolutionStatus(data)).toBe("Pending");
  });

  it("reads as Recovered when a past pullback has since been resolved", () => {
    const data = trendAnalysis({ trend_state: "uptrend", warning_flag: false, pullback_occurred_since_flip: true });
    expect(resolutionStatus(data)).toBe("Recovered");
  });

  it("reads as Invalidated on a downtrend regardless of the pullback fields", () => {
    const data = trendAnalysis({ trend_state: "downtrend", warning_flag: false, pullback_occurred_since_flip: true });
    expect(resolutionStatus(data)).toBe("Invalidated");
  });
});

describe("FRESHNESS_LABEL", () => {
  it("is context-aware per status instead of a single generic label", () => {
    expect(FRESHNESS_LABEL.NoPullback).toBe("Bars since last confirming swing");
    expect(FRESHNESS_LABEL.Pending).toBe("Bars since uptrend last confirmed");
    expect(FRESHNESS_LABEL.Recovered).toBe("Bars since recovery confirmed");
  });

  it("does not claim to measure the pullback's own start for Pending -- last_confirmed_swing is untouched by a warning firing", () => {
    expect(FRESHNESS_LABEL.Pending).not.toMatch(/pullback started/i);
  });
});

describe("invalidatedFreshnessText", () => {
  it("states how many bars ago the downtrend was confirmed", () => {
    expect(invalidatedFreshnessText(7)).toBe("Downtrend confirmed 7 bars ago.");
  });

  it("reads 0 bars ago distinctly from the unavailable case -- 0 is a real, meaningful count", () => {
    expect(invalidatedFreshnessText(0)).toBe("Downtrend confirmed 0 bars ago.");
  });

  it("falls back to an explicit unavailable message when bars_since_confirmation is null", () => {
    expect(invalidatedFreshnessText(null)).toBe("Downtrend confirmation date unavailable.");
  });
});
