// @vitest-environment jsdom
import { CandlestickSeries, createChart } from "lightweight-charts";
import { expect, it } from "vitest";

import { FvgZonesPrimitive } from "@/components/chart/FvgZonesPrimitive";
import type { ChartFvgOut } from "@/lib/api/types";

// The real lightweight-charts (5.2.0) under jsdom with a recording canvas context: the pane is 1000px wide, so the rectangles
// the primitive fills are real library coordinates (the unit test mocks logicalToCoordinate; this one pins that the real
// one, which answers 0 for a fractional logical, still yields finite, in-pane, non-empty rectangles).
it("draws a finite, in-pane, non-empty rectangle per zone through the real library", async () => {
  // Candle bodies are fillRects too, so keep only the ones painted in a zone fill color.
  const fills: { style: string; rect: number[] }[] = [];
  let fillStyle = "";
  const ctx: unknown = new Proxy(
    {},
    {
      get: (_t, k) =>
        k === "measureText"
          ? () => ({ width: 10 })
          : k === "canvas"
            ? document.createElement("canvas")
            : k === "fillRect"
              ? (...a: number[]) => fills.push({ style: fillStyle, rect: a })
              : () => ctx,
      set: (_t, k, v) => {
        if (k === "fillStyle") fillStyle = String(v);
        return true;
      },
    }
  );
  HTMLCanvasElement.prototype.getContext = (() => ctx) as never;
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };

  const el = document.createElement("div");
  document.body.appendChild(el);
  const chart = createChart(el, { width: 1000, height: 500 });
  const candle = chart.addSeries(CandlestickSeries, {});
  const bars: { time: string; open: number; high: number; low: number; close: number }[] = [];
  const d = new Date(Date.UTC(2026, 3, 15));
  while (bars.length < 126) {
    d.setUTCDate(d.getUTCDate() + 1);
    if (d.getUTCDay() === 0 || d.getUTCDay() === 6) continue;
    const p = 400 + bars.length * 0.3;
    bars.push({ time: d.toISOString().slice(0, 10), open: p, high: p + 3, low: p - 3, close: p + 1 });
  }
  candle.setData(bars as never);
  chart.timeScale().setVisibleLogicalRange({ from: -5, to: 130 } as never);
  const times = bars.map((b) => b.time);
  const zones: ChartFvgOut[] = [
    { side: "bullish", top: 412.14, bottom: 394.69, start_time: times[1], end_time: times[40] },
    { side: "bearish", top: 450, bottom: 440, start_time: times[31], end_time: null },
  ];
  const prim = new FvgZonesPrimitive({ bullish: "#0891B2", bearish: "#F472B6" });
  candle.attachPrimitive(prim);
  prim.setZones(zones, times);
  await new Promise((r) => setTimeout(r, 200));

  const paneWidth = chart.timeScale().width();
  const zoneFills = (style: string) => fills.filter((f) => f.style === style).map((f) => f.rect);
  const bull = zoneFills("rgba(8, 145, 178, 0.14)").at(-1);
  const bear = zoneFills("rgba(244, 114, 182, 0.14)").at(-1);
  expect(bull).toBeDefined();
  expect(bear).toBeDefined();
  for (const [x, y, w, h] of [bull!, bear!]) {
    for (const v of [x, y, w, h]) expect(Number.isFinite(v)).toBe(true);
    expect(w).toBeGreaterThan(0);
    expect(h).toBeGreaterThan(0);
    expect(x).toBeGreaterThanOrEqual(0);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(x + w).toBeLessThanOrEqual(paneWidth + 1);
  }
  chart.remove();
});
