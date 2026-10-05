import { describe, expect, it } from "vitest";

import { LevelTagsPrimitive } from "@/components/chart/LevelTagsPrimitive";

// A fake series: a 100 px pane whose scale maps price p to y = (100 - p) (higher price = higher up, 1 px per unit),
// so RSI 84.75 sits at y 15.25 and 80.81 at y 19.19 -- 3.94 px apart, well inside one 17 px tag.
function fakeSeries(height = 100) {
  return {
    getPane: () => ({ getHeight: () => height }),
    priceToCoordinate: (p: number) => 100 - p,
  };
}

const LEVELS = [
  { price: 80.81, backColor: "#52525b", textColor: "#fff" },
  { price: 84.75, backColor: "#52525b", textColor: "#fff" },
];

function attach(levels = LEVELS, series = fakeSeries()) {
  const p = new LevelTagsPrimitive(levels, () => 12);
  p.attached({ series } as never);
  p.updateAllViews();
  return p.priceAxisViews();
}

describe("LevelTagsPrimitive", () => {
  it("nudges a colliding pair apart: the upper line's tag up, the lower line's tag down, one tag height (17px) apart", () => {
    const [lower, upper] = attach();
    const yLower = lower.fixedCoordinate!()!;
    const yUpper = upper.fixedCoordinate!()!;
    expect(yLower - yUpper).toBeCloseTo(17);
    expect(yUpper).toBeCloseTo(15.25 - (17 - 3.94) / 2); // 84.75's tag moved up from its line (y 15.25)
    expect(yLower).toBeCloseTo(19.19 + (17 - 3.94) / 2); // 80.81's tag moved down from its line (y 19.19)
  });

  it("keeps each tag tied to its own line: its text is its own level, formatted like every axis price", () => {
    const [lower, upper] = attach();
    expect(lower.text()).toBe("80.81");
    expect(upper.text()).toBe("84.75");
    expect(lower.backColor()).toBe("#52525b");
    expect(lower.textColor()).toBe("#fff");
    expect(lower.tickVisible?.()).toBe(false);
  });

  it("does not move tags that already clear each other", () => {
    const [a, b] = attach([{ ...LEVELS[0], price: 50 }, { ...LEVELS[1], price: 80 }]);
    expect(a.fixedCoordinate!()).toBe(50);
    expect(b.fixedCoordinate!()).toBe(20);
  });

  it("hides until it has a series, and when a level cannot be placed", () => {
    const p = new LevelTagsPrimitive(LEVELS, () => 12);
    p.updateAllViews();
    expect(p.priceAxisViews().map((v) => v.visible?.())).toEqual([false, false]);
    const series = { ...fakeSeries(), priceToCoordinate: () => null };
    p.attached({ series } as never);
    p.updateAllViews();
    expect(p.priceAxisViews().map((v) => v.visible?.())).toEqual([false, false]);
  });
});
