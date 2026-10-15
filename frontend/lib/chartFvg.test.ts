import { describe, expect, it } from "vitest";

import { FVG_EDGE_ALPHA, FVG_FILL_ALPHA, fvgRect, fvgSpan, withAlpha } from "@/lib/chartFvg";

const BARS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]; // logical 0..4

describe("fvgSpan", () => {
  it("runs from c4's left edge to the ending bar's right edge", () => {
    expect(fvgSpan({ start_time: "2026-03-03", end_time: "2026-03-05" }, BARS)).toEqual({ left: 0.5, right: 3.5 });
  });

  it("keeps a zone that ends on c4 as a one-bar-wide sliver", () => {
    expect(fvgSpan({ start_time: "2026-03-04", end_time: "2026-03-04" }, BARS)).toEqual({ left: 1.5, right: 2.5 });
  });

  it("draws an open zone to the last bar's right edge", () => {
    expect(fvgSpan({ start_time: "2026-03-04", end_time: null }, BARS)).toEqual({ left: 1.5, right: 4.5 });
  });

  it("draws a zone whose c3 is the last bar one bar wide, one bar to the right of the last bar", () => {
    expect(fvgSpan({ start_time: "2026-03-09", end_time: null }, BARS)).toEqual({ left: 4.5, right: 5.5 });
  });

  it("skips a zone it cannot place", () => {
    expect(fvgSpan({ start_time: "2026-02-20", end_time: null }, BARS)).toBeNull(); // before the first bar, not a projection
    expect(fvgSpan({ start_time: "2026-03-03", end_time: "2026-03-10" }, BARS)).toBeNull(); // end is not a bar
    expect(fvgSpan({ start_time: "2026-03-05", end_time: "2026-03-03" }, BARS)).toBeNull(); // ends before it starts
    expect(fvgSpan({ start_time: "2026-03-03", end_time: null }, [])).toBeNull();
  });
});

describe("fvgRect", () => {
  it("maps the four converted edges to a rectangle, whichever way the prices map to y", () => {
    expect(fvgRect(10, 50, 20, 40)).toEqual({ x: 10, y: 20, width: 40, height: 20 });
    expect(fvgRect(10, 50, 40, 20)).toEqual({ x: 10, y: 20, width: 40, height: 20 });
  });

  it("is null when any coordinate is null", () => {
    expect(fvgRect(null, 50, 20, 40)).toBeNull();
    expect(fvgRect(10, null, 20, 40)).toBeNull();
    expect(fvgRect(10, 50, null, 40)).toBeNull();
    expect(fvgRect(10, 50, 20, null)).toBeNull();
  });

  it("is null for a degenerate box", () => {
    expect(fvgRect(10, 10, 20, 40)).toBeNull();
    expect(fvgRect(10, 50, 30, 30)).toBeNull();
  });
});

describe("withAlpha", () => {
  it("converts 6- and 3-digit hex to rgba", () => {
    expect(withAlpha("#0891B2", 0.14)).toBe("rgba(8, 145, 178, 0.14)");
    expect(withAlpha("#fff", 0.5)).toBe("rgba(255, 255, 255, 0.5)");
  });

  it("returns any other color string unchanged", () => {
    expect(withAlpha("rgb(1, 2, 3)", 0.5)).toBe("rgb(1, 2, 3)");
  });

  it("uses a faint fill and a stronger edge", () => {
    expect(FVG_FILL_ALPHA).toBe(0.14);
    expect(FVG_EDGE_ALPHA).toBeGreaterThanOrEqual(0.55);
    expect(FVG_EDGE_ALPHA).toBeLessThanOrEqual(0.6);
  });
});
