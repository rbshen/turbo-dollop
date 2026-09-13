import { describe, expect, it } from "vitest";

import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import {
  FRESHNESS_LABEL,
  invalidatedFreshnessText,
  pullbackHistoryPoints,
  resolutionStatus,
  rightNowDetailText,
  rightNowFreshnessCaption,
  rightNowStatusText,
} from "@/components/technical/TrendContinuationCard";
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
    trend_started: null,
    trend_started_is_lower_bound: null,
    pullback_history: [],
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

describe("pullbackHistoryPoints", () => {
  it("returns an empty timeline for an empty history", () => {
    expect(pullbackHistoryPoints([])).toEqual([]);
  });

  it("flattens each cycle into an alternating warning-then-resolved pair, in order", () => {
    const history: TrendAnalysisOut["pullback_history"] = [
      {
        warning_swing: { date: "2026-08-11", price: 204.75, margin: 11.22, atr: 5.2, ratio: 2.16, classification: "LH" },
        resolving_swing: { date: "2026-08-17", price: 197.82, margin: 29.46, atr: 4.85, ratio: 6.08, classification: "HL" },
      },
      {
        warning_swing: { date: "2026-08-24", price: 207.4, margin: 8.57, atr: 4.51, ratio: 1.9, classification: "LH" },
        resolving_swing: { date: "2026-09-02", price: 198.09, margin: 29.73, atr: 3.92, ratio: 7.58, classification: "HL" },
      },
    ];

    expect(pullbackHistoryPoints(history)).toEqual([
      { kind: "warning", date: "2026-08-11" },
      { kind: "resolved", date: "2026-08-17" },
      { kind: "warning", date: "2026-08-24" },
      { kind: "resolved", date: "2026-09-02" },
    ]);
  });
});

describe("rightNowStatusText", () => {
  it("reads the relabeled, plainer text while a pullback is in progress", () => {
    const data = trendAnalysis({ trend_state: "uptrend" });
    expect(rightNowStatusText(data, true)).toBe("Pulled back — hasn't made a new high yet");
  });

  it("reads a plain 'no pullback' line when nothing is currently active", () => {
    const data = trendAnalysis({ trend_state: "uptrend" });
    expect(rightNowStatusText(data, false)).toBe("No pullback currently active");
  });

  it("reads distinctly once the trend itself has reversed -- this card's dead-in-production branch, per technicalCardScope.ts, but still exercised directly here", () => {
    const data = trendAnalysis({ trend_state: "downtrend" });
    expect(rightNowStatusText(data, false)).toBe("Trend has reversed — no longer tracking a pullback here.");
  });
});

describe("rightNowDetailText", () => {
  it("names the actual lower high once a pullback is in progress", () => {
    const data = trendAnalysis({
      warning_swing: { date: "2026-08-24", price: 207.4, margin: 8.57, atr: 4.51, ratio: 1.9, classification: "LH" },
    });
    expect(rightNowDetailText(data, true)).toBe(`Lower high on ${fmtSwingDate("2026-08-24")} against the established uptrend.`);
  });

  it("has no detail line when no pullback is in progress", () => {
    const data = trendAnalysis({ warning_swing: null });
    expect(rightNowDetailText(data, false)).toBeNull();
  });

  it("has no detail line if in progress but warning_swing itself is somehow missing", () => {
    const data = trendAnalysis({ warning_swing: null });
    expect(rightNowDetailText(data, true)).toBeNull();
  });
});

describe("rightNowFreshnessCaption", () => {
  it("is null for Recovered -- that fact is folded onto the timeline's own last dot instead", () => {
    expect(rightNowFreshnessCaption("Recovered", "2026-09-02", 6)).toBeNull();
  });

  it("is null for Invalidated -- no reference-window framing applies there", () => {
    expect(rightNowFreshnessCaption("Invalidated", "2026-09-02", 6)).toBeNull();
  });

  it("renders the status-specific label alongside the date and bars-ago count for NoPullback", () => {
    expect(rightNowFreshnessCaption("NoPullback", "2026-08-20", 12)).toBe(
      `Bars since last confirming swing: ${fmtSwingDate("2026-08-20")} · 12 bars ago`
    );
  });

  it("renders the status-specific label for Pending", () => {
    expect(rightNowFreshnessCaption("Pending", "2026-08-05", 15)).toBe(`Bars since uptrend last confirmed: ${fmtSwingDate("2026-08-05")} · 15 bars ago`);
  });

  it("is null when there's no date to anchor it to (e.g. too-thin history)", () => {
    expect(rightNowFreshnessCaption("NoPullback", null, 12)).toBeNull();
  });

  it("is null when bars itself is unavailable", () => {
    expect(rightNowFreshnessCaption("NoPullback", "2026-08-20", null)).toBeNull();
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
