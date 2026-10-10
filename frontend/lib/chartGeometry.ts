// Pure geometry for the Dashboard chart primitives (components/charts/: ThresholdGauge, DivergingBar, StageTimeline, PriceRangeBar,
// Sparkline). No React, no DOM: every position is a percentage 0-100 so the components stay a thin layer of markup, and the maths is
// testable. docs/design-system-charts.md, "Dashboard primitives".

export type GaugeDirection = "ceiling" | "floor";
/** ok: on the safe side of the pass line. monitor: past the pass line, inside the hard limit (the amber zone). breach: past the hard limit. */
export type GaugeState = "ok" | "monitor" | "breach";

export function clampPct(pct: number): number {
  return Math.min(100, Math.max(0, pct));
}

/** Where a value sits relative to its lines. With one line only (hardLimit equal to passLine) there is no monitor zone: past it is a breach. */
export function gaugeState(value: number, passLine: number, hardLimit: number, direction: GaugeDirection): GaugeState {
  const past = (limit: number) => (direction === "ceiling" ? value > limit : value < limit);
  if (!past(passLine)) return "ok";
  return hardLimit !== passLine && !past(hardLimit) ? "monitor" : "breach";
}

/** The track runs 0 to this maximum: far enough that both lines and the value fit, without letting one extreme value squash the lines. */
export function gaugeScaleMax(value: number | null, passLine: number, hardLimit: number, direction: GaugeDirection): number {
  const v = value !== null && Number.isFinite(value) ? Math.max(value, 0) : 0;
  if (direction === "ceiling") {
    const far = Math.max(passLine, hardLimit);
    return Math.max(far * 1.5, Math.min(v * 1.1, far * 3));
  }
  const far = Math.max(passLine, hardLimit);
  return Math.max(far * 2, Math.min(v * 1.1, far * 4));
}

export interface GaugeGeometry {
  scaleMax: number;
  state: GaugeState | null;
  /** Fill width, 0-100 (null when there is no value). */
  fillPct: number | null;
  /** True when the value is past the end of the track (the fill is clamped; the label gets a "›"). */
  overflow: boolean;
  passPct: number;
  limitPct: number;
  /** The amber monitor zone between the two lines, or null when they coincide. */
  zone: { leftPct: number; widthPct: number } | null;
}

export function gaugeGeometry(value: number | null, passLine: number, hardLimit: number, direction: GaugeDirection): GaugeGeometry {
  const scaleMax = gaugeScaleMax(value, passLine, hardLimit, direction);
  const pct = (v: number) => clampPct((v / scaleMax) * 100);
  const hasValue = value !== null && Number.isFinite(value);
  const lo = Math.min(passLine, hardLimit);
  const hi = Math.max(passLine, hardLimit);
  return {
    scaleMax,
    state: hasValue ? gaugeState(value, passLine, hardLimit, direction) : null,
    fillPct: hasValue ? pct(value) : null,
    overflow: hasValue && value > scaleMax,
    passPct: pct(passLine),
    limitPct: pct(hardLimit),
    zone: hi === lo ? null : { leftPct: pct(lo), widthPct: pct(hi) - pct(lo) },
  };
}

export type DivergingTone = "ahead" | "behind" | "in_line";

/** Inside the band (inclusive, as the Stuck check's "in line") is in line; otherwise the sign decides. */
export function divergingTone(value: number, band: number): DivergingTone {
  if (Math.abs(value) <= band) return "in_line";
  return value > 0 ? "ahead" : "behind";
}

/** One symmetric half-scale (the axis runs -scale to +scale) shared by a stack of bars so they compare: the largest gap with a little
 * headroom, never under three times the band (so the band is always visible) and never under `floor`. */
export function divergingScale(values: Array<number | null | undefined>, band: number, floor = 5): number {
  const largest = Math.max(0, ...values.filter((v): v is number => typeof v === "number" && Number.isFinite(v)).map(Math.abs));
  return Math.max(largest * 1.15, band * 3, floor);
}

export interface DivergingGeometry {
  tone: DivergingTone | null;
  /** The bar spans from the centre (50) to this edge: 50-100 for a positive value, 0-50 for a negative one. */
  barFromPct: number;
  barWidthPct: number;
  overflow: boolean;
  /** The in-line band as a rectangle centred on the axis. */
  bandLeftPct: number;
  bandWidthPct: number;
}

export function divergingGeometry(value: number | null, band: number, scale: number): DivergingGeometry {
  const half = (v: number) => clampPct((Math.abs(v) / scale) * 100) / 2;
  const bandHalf = half(band);
  const base = { bandLeftPct: 50 - bandHalf, bandWidthPct: bandHalf * 2 };
  if (value === null || !Number.isFinite(value)) return { ...base, tone: null, barFromPct: 50, barWidthPct: 0, overflow: false };
  const width = half(value);
  return {
    ...base,
    tone: divergingTone(value, band),
    barFromPct: value >= 0 ? 50 : 50 - width,
    barWidthPct: width,
    overflow: Math.abs(value) > scale,
  };
}

// --- Stage timeline -------------------------------------------------------------------------------------------------------------

export interface StageWeek {
  week: string; // ISO date of the Monday the weekly bar is labelled with
  stage: string | null;
}

export interface StageRun {
  stage: string | null;
  weeks: number;
  /** Index of the run's first week in the series. */
  start: number;
}

/** Consecutive weeks of the same stage as one run (a null stage, before the engine is seeded, is a run of its own). */
export function groupStageRuns(weeks: StageWeek[]): StageRun[] {
  const runs: StageRun[] = [];
  weeks.forEach((w, i) => {
    const last = runs[runs.length - 1];
    if (last && last.stage === w.stage) last.weeks += 1;
    else runs.push({ stage: w.stage, weeks: 1, start: i });
  });
  return runs;
}

/** Where the since date falls on the strip, 0-100, and whether it is inside the window at all (older than the first week: pinned to 0, not inside). */
export function stageSincePosition(weeks: StageWeek[], since: string | null | undefined): { pct: number; inside: boolean } | null {
  if (!since || weeks.length === 0) return null;
  const index = weeks.findIndex((w) => w.week >= since);
  if (index === -1) return { pct: 100, inside: false };
  if (index === 0 && weeks[0].week > since) return { pct: 0, inside: false };
  return { pct: (index / weeks.length) * 100, inside: true };
}

// --- Price range bar ------------------------------------------------------------------------------------------------------------

export type BandPosition = "below" | "inside" | "above";

/** The valuation verdict's own rule (scoring/step3.py): at or under the low edge reads undervalued, at or over the high edge overvalued. */
export function bandPosition(price: number, fairValue: number, bandLow: number, bandHigh: number): BandPosition {
  const ratio = Math.round((price / fairValue) * 1e6) / 1e6;
  if (ratio <= bandLow) return "below";
  if (ratio >= bandHigh) return "above";
  return "inside";
}

export interface PriceRangeGeometry {
  fairPct: number;
  bandLeftPct: number;
  bandWidthPct: number;
  pricePct: number;
  position: BandPosition;
  /** price / fair value - 1, percent. */
  premiumPct: number;
}

/** The track covers the band and the price with 15% of the spread on each side, so the price is always on it. */
export function priceRangeGeometry(price: number, fairValue: number, bandLow: number, bandHigh: number): PriceRangeGeometry {
  const lowEdge = fairValue * bandLow;
  const highEdge = fairValue * bandHigh;
  const lo = Math.min(price, lowEdge);
  const hi = Math.max(price, highEdge);
  const pad = (hi - lo) * 0.15;
  const min = Math.max(0, lo - pad);
  const max = hi + pad;
  const pct = (v: number) => clampPct(((v - min) / (max - min)) * 100);
  return {
    fairPct: pct(fairValue),
    bandLeftPct: pct(lowEdge),
    bandWidthPct: pct(highEdge) - pct(lowEdge),
    pricePct: pct(price),
    position: bandPosition(price, fairValue, bandLow, bandHigh),
    premiumPct: (price / fairValue - 1) * 100,
  };
}

// --- Sparkline ------------------------------------------------------------------------------------------------------------------

export interface SparklineGeometry {
  /** SVG polyline `points` in a 100 x 100 box (y flipped), or null with fewer than two finite values. */
  points: string | null;
  /** The last point as percentages of the box, for an absolutely positioned end dot. */
  last: { xPct: number; yPct: number } | null;
}

export function sparklineGeometry(values: Array<number | null | undefined>): SparklineGeometry {
  const finite = values.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null));
  const present = finite.filter((v): v is number => v !== null);
  if (present.length < 2) return { points: null, last: null };
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const n = finite.length;
  const coords: Array<[number, number]> = [];
  finite.forEach((v, i) => {
    if (v === null) return;
    coords.push([(i / (n - 1)) * 100, 100 - ((v - min) / span) * 100]);
  });
  const lastCoord = coords[coords.length - 1];
  return {
    points: coords.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" "),
    last: { xPct: lastCoord[0], yPct: lastCoord[1] },
  };
}
