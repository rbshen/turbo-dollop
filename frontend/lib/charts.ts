/** "Nice" round-number tick values from 0 to a bit past `max`, for an axis
 * with no fixed tick set (unlike the margin chart's fixed 0/25/50/75/100). */
export function computeNiceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const rawStep = max / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const residual = rawStep / magnitude;
  let step: number;
  if (residual > 5) step = 10 * magnitude;
  else if (residual > 2) step = 5 * magnitude;
  else if (residual > 1) step = 2 * magnitude;
  else step = magnitude;

  const ticks: number[] = [];
  for (let t = 0; t <= max + step * 0.001; t += step) {
    ticks.push(Math.round(t / step) * step);
  }
  return ticks;
}
