import { describe, expect, it } from "vitest";

import {
  formatWeinsteinPendingCushion,
  formatWeinsteinPendingEtaScenario,
  formatWeinsteinSince,
  weinsteinPendingCushionIsThin,
  weinsteinPendingHasCushionEtaDivergence,
  weinsteinPendingTooltipLine,
  weinsteinUnavailableReason,
  WEINSTEIN_PENDING_LONG_ETA_WEEKS,
} from "@/lib/weinsteinStage";
import type { WeinsteinPendingEtaScenarioOut, WeinsteinPendingOut } from "@/lib/api/types";

const fmtDate = (iso: string) => iso; // identity, so assertions stay simple/exact

describe("formatWeinsteinSince", () => {
  it("reads as a precise date when the transition is known", () => {
    expect(formatWeinsteinSince("2024-03-04", false, fmtDate)).toBe("Since 2024-03-04");
  });

  it("reads as a lower bound when the true start predates the fetch window", () => {
    expect(formatWeinsteinSince("2024-03-04", true, fmtDate)).toBe("Since at least 2024-03-04");
  });
});

describe("weinsteinUnavailableReason", () => {
  it("reads as not_yet_computed when weeks_available itself is null -- a legacy/never-reprocessed row", () => {
    expect(weinsteinUnavailableReason(null)).toBe("not_yet_computed");
  });

  it("reads as insufficient_history when a real (sub-40) week count was found", () => {
    expect(weinsteinUnavailableReason(18)).toBe("insufficient_history");
  });

  it("reads as insufficient_history even for a count of exactly 0 -- 0 is a real, meaningful count, not a missing value", () => {
    expect(weinsteinUnavailableReason(0)).toBe("insufficient_history");
  });
});

// ---------------------------------------------------------------------------
// "Pending confirmation" + ETA
// ---------------------------------------------------------------------------

function scenario(overrides: Partial<WeinsteinPendingEtaScenarioOut>): WeinsteinPendingEtaScenarioOut {
  return {
    weeks_away: 1,
    projected_date: "2026-09-28",
    band_lapsed_before_confirmation: false,
    growth_rate_pct: 0,
    horizon_exceeded: false,
    ...overrides,
  };
}

function pending(overrides: Partial<WeinsteinPendingOut>): WeinsteinPendingOut {
  return {
    direction: "advance",
    since_date: "2026-09-07",
    since_is_lower_bound: false,
    band_cushion_pct: 15.5,
    typical_weekly_move_pct: 7.1,
    eta: { flat: scenario({}), trend_5: scenario({}), trend_13: scenario({}) },
    ...overrides,
  };
}

describe("formatWeinsteinPendingEtaScenario", () => {
  it("formats a confirming scenario as N week(s) away, with the projected date", () => {
    expect(formatWeinsteinPendingEtaScenario(scenario({ weeks_away: 1, projected_date: "2026-09-28" }), fmtDate)).toBe(
      "~1 week away (week of 2026-09-28)"
    );
    expect(formatWeinsteinPendingEtaScenario(scenario({ weeks_away: 3, projected_date: "2026-10-12" }), fmtDate)).toBe(
      "~3 weeks away (week of 2026-10-12)"
    );
  });

  it("reads as a plain horizon message when horizon_exceeded and the band never lapsed", () => {
    const text = formatWeinsteinPendingEtaScenario(
      scenario({ weeks_away: null, projected_date: null, horizon_exceeded: true, band_lapsed_before_confirmation: false }),
      fmtDate
    );
    expect(text).toBe("Doesn't confirm within 104 weeks.");
  });

  it("names the band-lapse mechanism when horizon_exceeded is caused by an aging price move -- worded scenario-agnostically, never 'flat price' specifically (round-2 validation fix)", () => {
    const text = formatWeinsteinPendingEtaScenario(
      scenario({ weeks_away: null, projected_date: null, horizon_exceeded: true, band_lapsed_before_confirmation: true }),
      fmtDate
    );
    expect(text).toContain("under this assumption");
    expect(text.toLowerCase()).not.toContain("flat price");
  });
});

describe("weinsteinPendingCushionIsThin", () => {
  it("is thin when the cushion is smaller than a typical weekly move", () => {
    expect(weinsteinPendingCushionIsThin(pending({ band_cushion_pct: 1.5, typical_weekly_move_pct: 7.1 }))).toBe(true);
  });

  it("is comfortable when the cushion exceeds a typical weekly move", () => {
    expect(weinsteinPendingCushionIsThin(pending({ band_cushion_pct: 15.5, typical_weekly_move_pct: 7.1 }))).toBe(false);
  });

  it("is false (not thin) when either figure is unavailable", () => {
    expect(weinsteinPendingCushionIsThin(pending({ band_cushion_pct: null }))).toBe(false);
    expect(weinsteinPendingCushionIsThin(pending({ typical_weekly_move_pct: null }))).toBe(false);
  });
});

describe("formatWeinsteinPendingCushion", () => {
  it("renders the cushion and typical-move figures with a thin/comfortable read", () => {
    expect(formatWeinsteinPendingCushion(pending({ band_cushion_pct: 15.5, typical_weekly_move_pct: 7.1 }))).toBe(
      "Band cushion: +15.5pp past threshold vs. a typical weekly move of ~7.1pp (comfortable)."
    );
    expect(formatWeinsteinPendingCushion(pending({ band_cushion_pct: 0.4, typical_weekly_move_pct: 6.3 }))).toBe(
      "Band cushion: +0.4pp past threshold vs. a typical weekly move of ~6.3pp (thin)."
    );
  });

  it("returns null when either figure is missing", () => {
    expect(formatWeinsteinPendingCushion(pending({ band_cushion_pct: null }))).toBeNull();
  });
});

describe("weinsteinPendingHasCushionEtaDivergence", () => {
  it("is true for a thin cushion combined with a long flat-scenario ETA (the JBL/IONQ/MPWR/TTWO shape)", () => {
    const p = pending({
      band_cushion_pct: 0.36,
      typical_weekly_move_pct: 6.3,
      eta: { flat: scenario({ weeks_away: WEINSTEIN_PENDING_LONG_ETA_WEEKS }) },
    });
    expect(weinsteinPendingHasCushionEtaDivergence(p)).toBe(true);
  });

  it("is false when the cushion is thin but the flat ETA is short -- no real divergence to flag", () => {
    const p = pending({
      band_cushion_pct: 0.36,
      typical_weekly_move_pct: 6.3,
      eta: { flat: scenario({ weeks_away: WEINSTEIN_PENDING_LONG_ETA_WEEKS - 1 }) },
    });
    expect(weinsteinPendingHasCushionEtaDivergence(p)).toBe(false);
  });

  it("is false when the cushion is comfortable, even with a long ETA", () => {
    const p = pending({
      band_cushion_pct: 15.5,
      typical_weekly_move_pct: 7.1,
      eta: { flat: scenario({ weeks_away: 13 }) },
    });
    expect(weinsteinPendingHasCushionEtaDivergence(p)).toBe(false);
  });

  it("is false when the flat scenario itself never confirms (horizon_exceeded, weeks_away null)", () => {
    const p = pending({
      band_cushion_pct: 0.36,
      typical_weekly_move_pct: 6.3,
      eta: { flat: scenario({ weeks_away: null, horizon_exceeded: true }) },
    });
    expect(weinsteinPendingHasCushionEtaDivergence(p)).toBe(false);
  });
});

describe("weinsteinPendingTooltipLine", () => {
  it("names the target stage and includes the flat-scenario ETA", () => {
    const line = weinsteinPendingTooltipLine(
      pending({ direction: "advance", eta: { flat: scenario({ weeks_away: 1, projected_date: "2026-09-28" }) } }),
      fmtDate
    );
    expect(line).toContain("Pending Stage 2 (Advance)");
    expect(line).toContain("~1 week away (week of 2026-09-28)");
    expect(line).toContain("not a prediction");
  });

  it("names Stage 4 (Decline) for the mirrored direction", () => {
    const line = weinsteinPendingTooltipLine(pending({ direction: "decline" }), fmtDate);
    expect(line).toContain("Pending Stage 4 (Decline)");
  });
});
