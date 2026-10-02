import { describe, expect, it } from "vitest";

import { etIsoToFakeUtc } from "@/lib/chartTime";
import { futureDateStrings, futureTimestamps, zoneExtensionPoints, zoneLinePoints } from "@/lib/chartZoneLines";

describe("zoneLinePoints", () => {
  it("daily/weekly: string comparison, unchanged -- every bar from the swing date onward", () => {
    const bars = [{ time: "2026-01-05" }, { time: "2026-01-06" }, { time: "2026-01-07" }];
    expect(zoneLinePoints(bars, "2026-01-06", 99.5)).toEqual([
      { time: "2026-01-06", value: 99.5 },
      { time: "2026-01-07", value: 99.5 },
    ]);
    expect(zoneLinePoints(bars, "2026-01-08", 99.5)).toEqual([]);
  });

  it("2H: numeric comparison -- the line starts at the swing CANDLE, not the day (several candles share a day)", () => {
    const iso = ["09:30", "11:30", "13:30", "15:30"].map((t) => `2026-09-29T${t}:00`);
    const bars = iso.map((t) => ({ time: etIsoToFakeUtc(t) as number }));
    const pts = zoneLinePoints(bars, etIsoToFakeUtc("2026-09-29T13:30:00"), 101);
    expect(pts.map((p) => p.time)).toEqual([bars[2].time, bars[3].time]);
    expect(pts.every((p) => p.value === 101)).toBe(true);
  });

  it("2H: a swing candle that is not in the bars still starts at the next bar (never throws, never NaN)", () => {
    const bars = [{ time: 100 }, { time: 200 }, { time: 300 }];
    expect(zoneLinePoints(bars, 150, 1).map((p) => p.time)).toEqual([200, 300]);
  });
});

describe("margin extension", () => {
  it("daily/weekly: future date strings, day or week increments (behaviour unchanged)", () => {
    expect(futureDateStrings("2026-01-30", 3, 1)).toEqual(["2026-01-31", "2026-02-01", "2026-02-02"]);
    expect(futureDateStrings("2026-01-05", 2, 7)).toEqual(["2026-01-12", "2026-01-19"]);
    const pts = [{ time: "2026-01-05", value: 7 }];
    expect(zoneExtensionPoints(pts, 10, "daily")).toHaveLength(10);
    expect(zoneExtensionPoints(pts, 8.29, "weekly")).toHaveLength(9); // ceil, as before
    expect(zoneExtensionPoints(pts, 8.29, "weekly")[0].time).toBe("2026-01-12");
  });

  it("2H: ceil(rightOffset) numeric timestamps, strictly increasing, no date strings", () => {
    const last = etIsoToFakeUtc("2026-10-01T15:30:00");
    const ext = zoneExtensionPoints([{ time: last, value: 42 }], 10, "2h");
    expect(ext).toHaveLength(10);
    expect(ext.every((p) => typeof p.time === "number" && p.value === 42)).toBe(true);
    const times = ext.map((p) => p.time as number);
    expect(times[0]).toBe(last + 7200);
    expect(times).toEqual([...times].sort((a, b) => a - b));
    expect(new Set(times).size).toBe(10);
    expect(futureTimestamps(0, 3, 60)).toEqual([60, 120, 180]);
  });

  it("is a no-op with no margin or no points", () => {
    expect(zoneExtensionPoints([{ time: 1, value: 1 }], 0, "2h")).toEqual([]);
    expect(zoneExtensionPoints([], 10, "2h")).toEqual([]);
  });
});
