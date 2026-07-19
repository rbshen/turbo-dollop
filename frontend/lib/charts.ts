export const BAR_WIDTH = 14;
export const BAR_GAP = 3;
export const DEFAULT_GROUP_GAP = 20;

function niceStep(rawStep: number): number {
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const residual = rawStep / magnitude;
  if (residual > 5) return 10 * magnitude;
  if (residual > 2) return 5 * magnitude;
  if (residual > 1) return 2 * magnitude;
  return magnitude;
}

/** "Nice" round-number tick values from 0 to a bit past `max`, for an axis
 * with no fixed tick set (unlike the margin chart's fixed 0/25/50/75/100). */
export function computeNiceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const step = niceStep(max / count);

  // Top tick must cover max (not just get close to it) so the largest bar in
  // the dataset never clips against the topmost gridline.
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let t = 0; t <= top + step * 0.001; t += step) {
    ticks.push(Math.round(t / step) * step);
  }
  return ticks;
}

/** Like computeNiceTicks, but supports a negative floor -- some metrics (e.g.
 * Cash Conversion Cycle) can be genuinely negative (a company that collects
 * from customers before paying suppliers). Falls back to computeNiceTicks
 * when min >= 0, which every other chart in the app relies on. */
export function computeNiceTicksRange(min: number, max: number, count = 4): number[] {
  if (min >= 0) return computeNiceTicks(max, count);
  const span = max - min;
  if (span <= 0) return [Math.floor(min), Math.ceil(max) || 1];
  const step = niceStep(span / count);
  const bottom = Math.floor(min / step) * step;
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let t = bottom; t <= top + step * 0.001; t += step) {
    ticks.push(Math.round(t / step) * step);
  }
  return ticks;
}
