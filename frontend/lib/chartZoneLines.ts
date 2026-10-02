import type { UTCTimestamp } from "lightweight-charts";

// LP zone lines on the Chart tab. A zone is drawn as a LineSeries that starts at its swing bar and runs to the last
// bar, then is extended into the empty right-offset margin (see TickerChart.tsx::extendZoneLinesToEdge for why).
// Daily/weekly bars carry "YYYY-MM-DD" strings, so "a bar at/after the swing" is a string comparison and the
// synthetic margin points are future DATE strings. The 2H·90D range carries UTCTimestamp numbers (fake-UTC, see
// lib/chartTime.ts): there everything is numeric -- no date strings, no day increments.

export type ChartTime = string | number;

export interface ZonePoint {
  time: ChartTime;
  value: number;
}

/** Points for one zone: every bar from the swing bar onward, at the zone's price. Works for either time kind
 * (both compare with `>=` in time order); the zone's swing time must be in the same encoding as the bars. */
export function zoneLinePoints(bars: { time: ChartTime }[], formedAt: ChartTime, price: number): ZonePoint[] {
  return bars.filter((b) => b.time >= formedAt).map((b) => ({ time: b.time, value: price }));
}

// Generates `count` distinct, strictly-increasing "YYYY-MM-DD" dates after `lastTime`, spaced `incrementDays` apart
// (moved here unchanged from TickerChart.tsx). lightweight-charts spaces points by ordinal position, so the actual
// calendar gap does not change how many pixels of margin they cover.
export function futureDateStrings(lastTime: string, count: number, incrementDays: number): string[] {
  const base = new Date(`${lastTime}T00:00:00Z`);
  const out: string[] = [];
  for (let i = 1; i <= count; i++) {
    const d = new Date(base);
    d.setUTCDate(d.getUTCDate() + incrementDays * i);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

/** 2H·90D margin points: `count` strictly-increasing UTCTimestamps after `lastTime`, 2 hours apart. Pure
 * numeric arithmetic -- the same ordinal-spacing argument as above makes the step size irrelevant to rendering. */
export function futureTimestamps(lastTime: number, count: number, stepSeconds = 7200): UTCTimestamp[] {
  const out: UTCTimestamp[] = [];
  for (let i = 1; i <= count; i++) out.push((lastTime + stepSeconds * i) as UTCTimestamp);
  return out;
}

/** The synthetic points that extend a zone line into the right-offset margin, in the line's own time encoding. */
export function zoneExtensionPoints(points: ZonePoint[], rightOffset: number, timeframe: string): ZonePoint[] {
  if (!rightOffset || rightOffset <= 0 || !points.length) return [];
  const count = Math.ceil(rightOffset);
  const last = points[points.length - 1];
  if (typeof last.time === "number") return futureTimestamps(last.time, count).map((time) => ({ time, value: last.value }));
  return futureDateStrings(last.time, count, timeframe === "weekly" ? 7 : 1).map((time) => ({ time, value: last.value }));
}
