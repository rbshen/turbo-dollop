import { describe, expect, it } from "vitest";

import { candleWindow, etIsoToFakeUtc, fakeUtcToEtIso, formatCandleLegendTime } from "@/lib/chartTime";

describe("etIsoToFakeUtc / fakeUtcToEtIso", () => {
  it("encodes the ET wall-clock as if it were UTC", () => {
    expect(etIsoToFakeUtc("1970-01-01T00:00:00")).toBe(0);
    expect(etIsoToFakeUtc("2026-01-05T09:30:00")).toBe(Date.UTC(2026, 0, 5, 9, 30) / 1000);
    expect(new Date(etIsoToFakeUtc("2026-09-29T11:30:00") * 1000).getUTCHours()).toBe(11); // the axis reads 11:30
  });

  it("round-trips every candle start", () => {
    for (const t of ["09:30", "11:30", "13:30", "15:30"]) {
      const iso = `2026-09-29T${t}:00`;
      expect(fakeUtcToEtIso(etIsoToFakeUtc(iso))).toBe(iso);
    }
  });

  // US DST switches: 2026-03-08 (spring forward) and 2026-11-01 (fall back). A real-UTC encoding would put the
  // Monday-after 09:30 open 4 or 5 hours off; wall-clock encoding never does. Neither switch date is a session
  // (both are Sundays), so the days either side are what matter.
  it.each([
    ["2026-03-06T15:30:00", "2026-03-09T09:30:00", 2 * 86400 + 18 * 3600], // Fri close -> Mon open across spring-forward
    ["2026-10-30T15:30:00", "2026-11-02T09:30:00", 2 * 86400 + 18 * 3600], // across fall-back
    ["2026-03-09T09:30:00", "2026-03-09T11:30:00", 2 * 3600], // a normal day right after the switch
    ["2026-11-02T13:30:00", "2026-11-02T15:30:00", 2 * 3600],
  ])("%s -> %s is pure wall-clock arithmetic (%i s)", (a, b, diff) => {
    expect(etIsoToFakeUtc(b) - etIsoToFakeUtc(a)).toBe(diff);
  });

  it("keeps the 4 candles of a day strictly increasing on DST-adjacent days", () => {
    for (const day of ["2026-03-06", "2026-03-09", "2026-10-30", "2026-11-02"]) {
      const times = ["09:30", "11:30", "13:30", "15:30"].map((t) => etIsoToFakeUtc(`${day}T${t}:00`));
      expect(times).toEqual([...times].sort((x, y) => x - y));
      expect(new Set(times).size).toBe(4);
    }
  });

  it("rejects anything that is not a naive ET ISO string (no silent NaN on the chart)", () => {
    expect(() => etIsoToFakeUtc("2026-09-29")).toThrow();
    expect(() => etIsoToFakeUtc("2026-09-29T11:30:00Z")).toThrow();
    expect(() => etIsoToFakeUtc("2026-09-29 11:30:00")).toThrow();
  });
});

describe("candle window legend", () => {
  it("maps each candle start to its full window, the last one being the short 15:30-16:00 candle", () => {
    expect(candleWindow("2026-09-29T09:30:00")).toEqual({ start: "09:30", end: "11:30" });
    expect(candleWindow("2026-09-29T11:30:00")).toEqual({ start: "11:30", end: "13:30" });
    expect(candleWindow("2026-09-29T13:30:00")).toEqual({ start: "13:30", end: "15:30" });
    expect(candleWindow("2026-09-29T15:30:00")).toEqual({ start: "15:30", end: "16:00" });
  });

  it("formats the date (with weekday) and the window", () => {
    expect(formatCandleLegendTime("2026-09-29T11:30:00")).toBe("Tue Sep 29 · 11:30–13:30 ET");
    expect(formatCandleLegendTime("2026-10-02T15:30:00")).toBe("Fri Oct 2 · 15:30–16:00 ET");
    expect(formatCandleLegendTime("2026-03-09T09:30:00")).toBe("Mon Mar 9 · 09:30–11:30 ET");
  });

  it("falls back to the raw string for something it cannot parse", () => {
    expect(formatCandleLegendTime("nope")).toBe("nope");
  });
});
