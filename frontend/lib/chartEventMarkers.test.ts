import { describe, expect, it } from "vitest";

import {
  buildDividendMarkers,
  buildEarningsMarkers,
  describeEventMarker,
  epsSurprisePct,
  fmtEventDate,
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

describe("marker builders", () => {
  it("earnings: circle above the bar, 'E', id keyed to kind + bar time", () => {
    const [m] = buildEarningsMarkers(earnings, "#22d3ee");
    expect(m).toMatchObject({
      id: "earnings:2026-07-27",
      time: "2026-07-27",
      position: "aboveBar",
      shape: "circle",
      text: "E",
      color: "#22d3ee",
    });
  });

  it("dividends: square below the bar, 'D', id keyed to kind + bar time", () => {
    const [m] = buildDividendMarkers(dividends, "#a78bfa");
    expect(m).toMatchObject({
      id: "dividend:2026-08-10",
      time: "2026-08-10",
      position: "belowBar",
      shape: "square",
      text: "D",
      color: "#a78bfa",
    });
  });

  it("the two kinds never share an id, even on the same bar", () => {
    const e = buildEarningsMarkers([{ time: "2026-08-10", event_date: "2026-08-10", eps_actual: 1, eps_estimated: 1 }], "#000");
    const d = buildDividendMarkers([{ time: "2026-08-10", event_date: "2026-08-10", amount: 1 }], "#000");
    expect(e[0].id).not.toBe(d[0].id);
  });

  it("an empty list builds an empty marker array", () => {
    expect(buildEarningsMarkers([], "#000")).toEqual([]);
    expect(buildDividendMarkers([], "#000")).toEqual([]);
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
