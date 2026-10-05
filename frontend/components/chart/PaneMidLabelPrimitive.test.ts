import { describe, expect, it } from "vitest";

import { PaneMidLabelPrimitive } from "@/components/chart/PaneMidLabelPrimitive";

// A fake series: a pane `height` px tall whose scale maps y linearly onto [lo, hi] (y = 0 is hi).
function fakeSeries(height: number, lo: number, hi: number) {
  return {
    getPane: () => ({ getHeight: () => height }),
    coordinateToPrice: (y: number) => (height > 0 ? hi - (y / height) * (hi - lo) : null),
  };
}

function attach(series: ReturnType<typeof fakeSeries>) {
  const p = new PaneMidLabelPrimitive(() => "#9499a0", () => "#080b11");
  p.attached({ series } as never);
  p.updateAllViews();
  return { p, view: p.priceAxisViews()[0] };
}

describe("PaneMidLabelPrimitive", () => {
  it("labels the price at the middle of the pane's visible range, at exactly half the pane height", () => {
    const { view } = attach(fakeSeries(100, 0, 100));
    expect(view.text()).toBe("50.00");
    expect(view.fixedCoordinate?.()).toBe(50);
    expect(view.visible?.()).toBe(true);
    expect(view.tickVisible?.()).toBe(false);
    expect(view.textColor()).toBe("#9499a0");
    expect(view.backColor()).toBe("#080b11"); // page color: reads as a plain tick label
  });

  it("is the midpoint of an arbitrary visible range (ADX/WVF), formatted like every axis price", () => {
    expect(attach(fakeSeries(100, 8, 61)).view.text()).toBe("34.50");
    expect(attach(fakeSeries(100, -1.2, 4.4)).view.text()).toBe("1.60");
    expect(attach(fakeSeries(100, 0.12, 0.7)).view.text()).toBe("0.41");
  });

  it("follows the scale on the next update, and hides when there is no pane height or no series", () => {
    const series = fakeSeries(100, 0, 100);
    const { p, view } = attach(series);
    series.coordinateToPrice = (y) => 20 - (y / 100) * 10;
    p.updateAllViews();
    expect(view.text()).toBe("15.00");
    expect(attach(fakeSeries(0, 0, 100)).view.visible?.()).toBe(false);
    p.detached();
    p.updateAllViews();
    expect(view.visible?.()).toBe(false);
  });
});
