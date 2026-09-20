import { describe, expect, it } from "vitest";

import {
  buildDividendLabels,
  buildEarningsLabels,
  describeEventMarker,
  epsSurprisePct,
  EVENT_LABEL_FLOOR_PX,
  EVENT_LABEL_FONT_PX,
  EVENT_LABEL_HIT_HALF_HEIGHT_PX,
  EVENT_LABEL_HIT_HALF_WIDTH_PX,
  EVENT_LABEL_STACK_PX,
  eventLabelCenterY,
  eventTooltipPlacement,
  fmtEventDate,
  hitTestEventLabels,
  TOOLTIP_FLIP_MARGIN_PX,
  TOOLTIP_OFFSET_PX,
} from "@/lib/chartEventMarkers";
import type { ChartDividendMarkerOut, ChartEarningsMarkerOut } from "@/lib/api/types";

const earnings: ChartEarningsMarkerOut[] = [
  { time: "2026-07-27", event_date: "2026-07-30", eps_actual: 1.8, eps_estimated: 1.7 },
  { time: "2026-04-30", event_date: "2026-04-30", eps_actual: 1.5, eps_estimated: null },
];
const dividends: ChartDividendMarkerOut[] = [
  { time: "2026-08-10", event_date: "2026-08-10", amount: 0.27 },
  { time: "2019-08-05", event_date: "2019-08-09", amount: 0.1925 },
];

const PANE_H = 560;

describe("label builders", () => {
  it("earnings: a bare 'E' keyed to kind + bar time, on the row", () => {
    const [l] = buildEarningsLabels(earnings, "#22d3ee");
    expect(l).toEqual({ id: "earnings:2026-07-27", time: "2026-07-27", text: "E", color: "#22d3ee", stackSlot: 0 });
  });

  it("dividends: a bare 'D' keyed to kind + bar time, on the row", () => {
    const [l] = buildDividendLabels(dividends, "#a78bfa");
    expect(l).toEqual({ id: "dividend:2026-08-10", time: "2026-08-10", text: "D", color: "#a78bfa", stackSlot: 0 });
  });

  it("labels carry no shape/position/size fields -- letters only", () => {
    const [e] = buildEarningsLabels(earnings, "#000");
    const [d] = buildDividendLabels(dividends, "#000");
    for (const l of [e, d]) {
      expect(l).not.toHaveProperty("shape");
      expect(l).not.toHaveProperty("position");
      expect(l).not.toHaveProperty("size");
    }
  });

  it("the two kinds never share an id, even on the same bar", () => {
    const e = buildEarningsLabels([{ time: "2026-08-10", event_date: "2026-08-10", eps_actual: 1, eps_estimated: 1 }], "#000");
    const d = buildDividendLabels([{ time: "2026-08-10", event_date: "2026-08-10", amount: 1 }], "#000");
    expect(e[0].id).not.toBe(d[0].id);
  });

  it("a dividend on the same bar as an earnings report is stacked one slot up; others stay on the row", () => {
    const sameBar = [{ time: "2026-07-27", event_date: "2026-07-27", amount: 0.5 }];
    expect(buildDividendLabels(sameBar, "#000", earnings)[0].stackSlot).toBe(1);
    expect(buildDividendLabels(sameBar, "#000", [])[0].stackSlot).toBe(0);
    expect(buildDividendLabels(dividends, "#000", earnings).map((l) => l.stackSlot)).toEqual([0, 0]);
  });

  it("an empty list builds an empty array", () => {
    expect(buildEarningsLabels([], "#000")).toEqual([]);
    expect(buildDividendLabels([], "#000")).toEqual([]);
  });
});

describe("row geometry", () => {
  it("the letter's box bottom sits exactly the floor gap above the pane's real bottom edge", () => {
    const y = eventLabelCenterY(PANE_H, 0);
    expect(y + EVENT_LABEL_FONT_PX / 2).toBe(PANE_H - EVENT_LABEL_FLOOR_PX);
  });

  it("depends only on the pane's height: the row tracks the bottom as the pane resizes", () => {
    expect(eventLabelCenterY(PANE_H + 40, 0) - eventLabelCenterY(PANE_H, 0)).toBe(40);
  });

  it("a stacked label sits one stack step higher, clear of the letter below it", () => {
    expect(eventLabelCenterY(PANE_H, 0) - eventLabelCenterY(PANE_H, 1)).toBe(EVENT_LABEL_STACK_PX);
    expect(EVENT_LABEL_STACK_PX).toBeGreaterThanOrEqual(EVENT_LABEL_FONT_PX);
  });

  it("the letters are bigger than the chart's 12px default", () => {
    expect(EVENT_LABEL_FONT_PX).toBeGreaterThan(12);
  });
});

describe("hitTestEventLabels", () => {
  const placed = [
    { id: "earnings:a", x: 100, y: 540 },
    { id: "dividend:a", x: 100, y: 522 },
    { id: "earnings:b", x: 300, y: 540 },
  ];

  it("resolves a point on a label's box to its id", () => {
    expect(hitTestEventLabels(placed, 300, 540)).toBe("earnings:b");
    expect(hitTestEventLabels(placed, 300 + EVENT_LABEL_HIT_HALF_WIDTH_PX, 540 - EVENT_LABEL_HIT_HALF_HEIGHT_PX)).toBe("earnings:b");
  });

  it("misses just outside the box, and anywhere else", () => {
    expect(hitTestEventLabels(placed, 300 + EVENT_LABEL_HIT_HALF_WIDTH_PX + 1, 540)).toBeNull();
    expect(hitTestEventLabels(placed, 300, 540 + EVENT_LABEL_HIT_HALF_HEIGHT_PX + 1)).toBeNull();
    expect(hitTestEventLabels(placed, 200, 300)).toBeNull();
    expect(hitTestEventLabels([], 100, 540)).toBeNull();
  });

  it("stacked labels on one bar are told apart, nearest centre winning where boxes overlap", () => {
    expect(hitTestEventLabels(placed, 100, 541)).toBe("earnings:a");
    expect(hitTestEventLabels(placed, 100, 521)).toBe("dividend:a");
    // Points between the two centres (540 vs 522) resolve to whichever letter's box they fall in.
    expect(hitTestEventLabels(placed, 100, 532)).toBe("earnings:a");
    expect(hitTestEventLabels(placed, 100, 529)).toBe("dividend:a");
  });
});

describe("eventTooltipPlacement", () => {
  it("sits above and to the right of the cursor by default", () => {
    const p = eventTooltipPlacement(300, 540, 1000);
    expect(p).toEqual({ left: 300 + TOOLTIP_OFFSET_PX, top: 540 - TOOLTIP_OFFSET_PX, transform: "translate(0, -100%)" });
  });

  it("flips to the cursor's left inside the right-edge margin, still above", () => {
    const p = eventTooltipPlacement(1000 - TOOLTIP_FLIP_MARGIN_PX + 1, 540, 1000);
    expect(p.left).toBe(1000 - TOOLTIP_FLIP_MARGIN_PX + 1 - TOOLTIP_OFFSET_PX);
    expect(p.transform).toBe("translate(-100%, -100%)");
    expect(p.top).toBe(540 - TOOLTIP_OFFSET_PX);
  });

  it("does not flip exactly at the margin boundary", () => {
    expect(eventTooltipPlacement(1000 - TOOLTIP_FLIP_MARGIN_PX, 100, 1000).transform).toBe("translate(0, -100%)");
  });
});

describe("describeEventMarker", () => {
  it("earnings: shows the real report date (not the bar time), EPS, estimate and surprise", () => {
    const t = describeEventMarker("earnings:2026-07-27", earnings, dividends);
    expect(t).toEqual({
      title: "Earnings · Jul 30, 2026",
      lines: ["EPS 1.80", "Estimate 1.70", "Surprise +5.9%"],
    });
  });

  it("earnings without an estimate omits the estimate and surprise lines", () => {
    const t = describeEventMarker("earnings:2026-04-30", earnings, dividends);
    expect(t?.lines).toEqual(["EPS 1.50"]);
  });

  it("a miss reads as a negative surprise", () => {
    const t = describeEventMarker(
      "earnings:2026-01-01",
      [{ time: "2026-01-01", event_date: "2026-01-01", eps_actual: 0.9, eps_estimated: 1.0 }],
      []
    );
    expect(t?.lines).toContain("Surprise -10.0%");
  });

  it("dividends: ex-date title, sub-cent precision kept, currency-aware", () => {
    expect(describeEventMarker("dividend:2026-08-10", earnings, dividends)).toEqual({
      title: "Ex-dividend · Aug 10, 2026",
      lines: ["$0.27 per share"],
    });
    expect(describeEventMarker("dividend:2019-08-05", earnings, dividends, "USD")?.lines).toEqual(["$0.1925 per share"]);
    expect(describeEventMarker("dividend:2026-08-10", earnings, dividends, "HKD")?.lines[0]).toMatch(/^HK\$0\.27/);
  });

  it("returns null for ids that aren't ours or don't resolve", () => {
    expect(describeEventMarker(undefined, earnings, dividends)).toBeNull();
    expect(describeEventMarker("", earnings, dividends)).toBeNull();
    expect(describeEventMarker("bb_rsi:2026-07-27", earnings, dividends)).toBeNull();
    expect(describeEventMarker("earnings:1999-01-01", earnings, dividends)).toBeNull();
    expect(describeEventMarker("dividend:1999-01-01", earnings, dividends)).toBeNull();
  });
});

describe("helpers", () => {
  it("epsSurprisePct is undefined-safe: no estimate or a zero estimate yields null", () => {
    expect(epsSurprisePct(1, null)).toBeNull();
    expect(epsSurprisePct(1, 0)).toBeNull();
    expect(epsSurprisePct(1.1, 1)).toBeCloseTo(10);
    // A loss narrower than estimated is a beat: -0.5 vs -1.0
    expect(epsSurprisePct(-0.5, -1)).toBeCloseTo(50);
  });

  it("fmtEventDate is timezone-stable and tolerates garbage", () => {
    expect(fmtEventDate("2026-01-01")).toBe("Jan 1, 2026");
    expect(fmtEventDate("nonsense")).toBe("nonsense");
  });
});
