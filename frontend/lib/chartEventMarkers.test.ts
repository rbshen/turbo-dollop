import { describe, expect, it } from "vitest";

import {
  buildDividendMarkers,
  buildEarningsMarkers,
  describeEventMarker,
  epsSurprisePct,
  EVENT_ROW_FLOOR_PX,
  EVENT_ROW_STACK_PX,
  eventRowPrice,
  eventTooltipPlacement,
  fmtEventDate,
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

const PANE_H = 580;

describe("marker builders", () => {
  it("earnings: circle on the fixed event row, 'E', id keyed to kind + bar time", () => {
    const [m] = buildEarningsMarkers(earnings, "#22d3ee", PANE_H);
    expect(m).toMatchObject({
      id: "earnings:2026-07-27",
      time: "2026-07-27",
      position: "atPriceTop",
      shape: "circle",
      text: "E",
      color: "#22d3ee",
    });
  });

  it("dividends: square on the same fixed event row, 'D', id keyed to kind + bar time", () => {
    const [m] = buildDividendMarkers(dividends, "#a78bfa", PANE_H);
    expect(m).toMatchObject({
      id: "dividend:2026-08-10",
      time: "2026-08-10",
      position: "atPriceTop",
      shape: "square",
      text: "D",
      color: "#a78bfa",
    });
  });

  it("markers are pinned by price on the event-row scale, never relative to a bar (no aboveBar/belowBar/inBar)", () => {
    const all = [...buildEarningsMarkers(earnings, "#000", PANE_H), ...buildDividendMarkers(dividends, "#000", PANE_H)];
    for (const m of all) {
      expect(m.position).toBe("atPriceTop");
      expect(typeof m.price).toBe("number");
    }
    // Same row for both kinds on non-colliding bars, at the floor: price * (H - 1) recovers the pixel offset.
    const e = buildEarningsMarkers(earnings, "#000", PANE_H)[0];
    const d = buildDividendMarkers(dividends, "#000", PANE_H)[0];
    expect(e.price).toBe(d.price);
    expect(e.price * (PANE_H - 1)).toBeCloseTo(EVENT_ROW_FLOOR_PX);
  });

  it("the row's price does not depend on any candle price -- only on the pane height", () => {
    expect(eventRowPrice(6, 580)).toBeCloseTo(6 / 579);
    expect(eventRowPrice(6, 300)).toBeGreaterThan(eventRowPrice(6, 580));
    // Stays inside the pinned 0..1 range for any sane offset, so it maps onto the pane rather than off it.
    expect(eventRowPrice(EVENT_ROW_FLOOR_PX + EVENT_ROW_STACK_PX, PANE_H)).toBeLessThan(1);
    expect(eventRowPrice(EVENT_ROW_FLOOR_PX, PANE_H)).toBeGreaterThan(0);
  });

  it("the two kinds never share an id, even on the same bar", () => {
    const e = buildEarningsMarkers([{ time: "2026-08-10", event_date: "2026-08-10", eps_actual: 1, eps_estimated: 1 }], "#000", PANE_H);
    const d = buildDividendMarkers([{ time: "2026-08-10", event_date: "2026-08-10", amount: 1 }], "#000", PANE_H);
    expect(e[0].id).not.toBe(d[0].id);
  });

  it("a dividend on the same bar as an earnings report is stacked one slot above it; others stay on the row", () => {
    const sameBar = [{ time: "2026-07-27", event_date: "2026-07-27", amount: 0.5 }];
    const [stacked] = buildDividendMarkers(sameBar, "#000", PANE_H, earnings);
    const [alone] = buildDividendMarkers(sameBar, "#000", PANE_H, []);
    const [e] = buildEarningsMarkers(earnings, "#000", PANE_H);
    expect(stacked.price).toBeGreaterThan(e.price);
    expect((stacked.price - e.price) * (PANE_H - 1)).toBeCloseTo(EVENT_ROW_STACK_PX);
    expect(alone.price).toBe(e.price);
    // A dividend on a different bar is unaffected by the earnings list.
    const [other] = buildDividendMarkers(dividends, "#000", PANE_H, earnings);
    expect(other.price).toBe(e.price);
  });

  it("an empty list builds an empty marker array", () => {
    expect(buildEarningsMarkers([], "#000", PANE_H)).toEqual([]);
    expect(buildDividendMarkers([], "#000", PANE_H)).toEqual([]);
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
