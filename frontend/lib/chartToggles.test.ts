import { describe, expect, it } from "vitest";

import { DEFAULT_SIGNAL_TOGGLES, effectiveToggles, isToggleOffered, visibleToggleOptions } from "@/lib/chartToggles";
import type { SignalToggles } from "@/lib/chartToggles";

const labels = (range: Parameters<typeof visibleToggleOptions>[0], isEtf = false) => visibleToggleOptions(range, isEtf).map((o) => o.label);

describe("which toggles each range offers", () => {
  it("2H·90D offers exactly BB+RSI, Warren, LP Support and LP Resistance", () => {
    expect(labels("2H_90D")).toEqual(["BB+RSI", "Warren", "LP Support", "LP Resistance"]);
    expect(labels("2H_90D", true)).toEqual(["BB+RSI", "Warren", "LP Support", "LP Resistance"]);
  });

  it("daily ranges keep their ten toggles (Stage hidden); the ETF page drops Earnings", () => {
    for (const r of ["D_6M", "D_1Y", "D_2Y"] as const) {
      expect(labels(r)).toEqual(["BB+RSI", "Warren", "Earnings", "Dividends", "LP Support", "LP Resistance", "BB", "EMA 21", "SMA 50", "SMA 200"]);
      expect(labels(r, true)).not.toContain("Earnings");
    }
  });

  it("Stage exists on the weekly range only", () => {
    expect(labels("W_4Y")).toContain("Stage");
    expect(isToggleOffered("stage", "D_1Y", false)).toBe(false);
    expect(isToggleOffered("stage", "2H_90D", false)).toBe(false);
  });
});

describe("effectiveToggles", () => {
  const ALL_ON: SignalToggles = { ...DEFAULT_SIGNAL_TOGGLES, stage: true };

  it("forces every toggle the range does not offer off, whatever was saved", () => {
    const e = effectiveToggles(ALL_ON, "2H_90D", false);
    expect(e).toMatchObject({ bbRsi: true, warren: true, lpSupport: true, lpResistance: true });
    expect(e).toMatchObject({ earnings: false, dividends: false, bollinger: false, ema21: false, sma50: false, sma200: false, stage: false });
  });

  it("an offered toggle follows its saved value", () => {
    const e = effectiveToggles({ ...ALL_ON, warren: false, lpSupport: false }, "2H_90D", false);
    expect(e.warren).toBe(false);
    expect(e.lpSupport).toBe(false);
    expect(e.bbRsi).toBe(true);
  });

  it("does not mutate the saved toggles, so switching back restores them", () => {
    const saved = { ...ALL_ON, ema21: true, sma200: false };
    const snapshot = { ...saved };
    effectiveToggles(saved, "2H_90D", false);
    expect(saved).toEqual(snapshot);
    expect(effectiveToggles(saved, "D_1Y", false)).toMatchObject({ ema21: true, sma200: false });
  });

  it("matches the previous per-range behaviour on the existing ranges (Stage weekly-only, Earnings off for ETFs)", () => {
    expect(effectiveToggles(ALL_ON, "D_1Y", false).stage).toBe(false);
    expect(effectiveToggles(ALL_ON, "W_4Y", false).stage).toBe(true);
    expect(effectiveToggles(ALL_ON, "D_6M", true).earnings).toBe(false);
    expect(effectiveToggles(ALL_ON, "D_6M", false).earnings).toBe(true);
  });
});
