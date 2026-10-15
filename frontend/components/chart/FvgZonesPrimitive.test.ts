import { describe, expect, it } from "vitest";

import { FvgZonesPrimitive } from "@/components/chart/FvgZonesPrimitive";
import type { ChartFvgOut } from "@/lib/api/types";

const BARS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"];
const COLORS = { bullish: "#0891b2", bearish: "#f472b6" };

// Bar i is at x = 10 * i + 5 (so its edges are 10 * i and 10 * i + 10); price p is at y = 100 - p.
function setup(prices: (p: number) => number | null = (p) => 100 - p) {
  const calls: unknown[][] = [];
  const ctx = new Proxy(
    { fillStyle: "", strokeStyle: "", lineWidth: 0 },
    {
      get: (t, k: string) => (k in t ? (t as Record<string, unknown>)[k] : (...a: unknown[]) => calls.push([k, ...a])),
      set: (t, k: string, v) => {
        (t as Record<string, unknown>)[k] = v;
        if (k === "fillStyle" || k === "strokeStyle") calls.push([k, v]);
        return true;
      },
    }
  );
  const p = new FvgZonesPrimitive(COLORS);
  p.attached({
    chart: { timeScale: () => ({ logicalToCoordinate: (l: number) => 10 * l + 5 }) },
    series: { priceToCoordinate: prices },
    requestUpdate: () => {},
  } as never);
  const draw = () => {
    calls.length = 0;
    const renderer = p.paneViews()[0].renderer()!;
    renderer.draw({ useBitmapCoordinateSpace: (f: (s: unknown) => void) => f({ context: ctx, horizontalPixelRatio: 1, verticalPixelRatio: 1 }) } as never);
    return calls;
  };
  return { p, draw };
}

const BULL: ChartFvgOut = { side: "bullish", top: 60, bottom: 40, start_time: "2026-03-03", end_time: "2026-03-04" };
const BEAR: ChartFvgOut = { side: "bearish", top: 80, bottom: 70, start_time: "2026-03-05", end_time: null };

describe("FvgZonesPrimitive", () => {
  it("draws on the bottom layer and contributes nothing to autoscale", () => {
    const { p } = setup();
    expect(p.paneViews()[0].zOrder?.()).toBe("bottom");
    expect((p as unknown as { autoscaleInfo?: unknown }).autoscaleInfo).toBeUndefined();
  });

  it("fills each zone between its c4 left edge and ending right edge, in its own side's color at the fill alpha", () => {
    const { p, draw } = setup();
    p.setZones([BULL], BARS);
    const calls = draw();
    expect(calls).toContainEqual(["fillStyle", "rgba(8, 145, 178, 0.14)"]);
    expect(calls).toContainEqual(["fillRect", 10, 40, 20, 20]); // bars 1..2: edges 10..30; y 100-60..100-40
    expect(calls).toContainEqual(["strokeStyle", "rgba(8, 145, 178, 0.58)"]);
  });

  it("draws dashed top and bottom edge lines only (no sides)", () => {
    const { p, draw } = setup();
    p.setZones([BULL], BARS);
    const calls = draw();
    expect(calls.filter((c) => c[0] === "setLineDash").some((c) => (c[1] as number[]).length === 2)).toBe(true);
    const moves = calls.filter((c) => c[0] === "moveTo");
    expect(moves).toHaveLength(2);
    expect(moves.map((m) => m[2] as number)).toEqual([40.5, 60.5]);
  });

  it("draws overlapping zones all, bearish in the bearish color, an open zone to the last bar's right edge", () => {
    const { p, draw } = setup();
    p.setZones([BULL, BEAR], BARS);
    const calls = draw();
    expect(calls.filter((c) => c[0] === "fillRect")).toHaveLength(2);
    expect(calls).toContainEqual(["fillStyle", "rgba(244, 114, 182, 0.14)"]);
    expect(calls).toContainEqual(["fillRect", 30, 20, 20, 10]); // bar 3 left edge (30) to bar 4 right edge (50)
  });

  it("skips a zone whose price has no coordinate, and draws nothing for an empty list", () => {
    const { p, draw } = setup((price) => (price === 60 ? null : 100 - price));
    p.setZones([BULL, BEAR], BARS);
    expect(draw().filter((c) => c[0] === "fillRect")).toHaveLength(1);
    p.setZones([], BARS);
    expect(draw().filter((c) => c[0] === "fillRect")).toHaveLength(0);
  });
});
