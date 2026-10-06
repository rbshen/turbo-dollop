// Two numeric rules of the backend's Python, reproduced exactly so the live Analysis tab and the stored Overall score
// (backend/scoring/overall.py) can never differ by a point: Python's round() and Python 3.12's sum() of floats.

/** Python's round(x) for a float: the nearest integer, an exact .5 tie going to the EVEN neighbour (2.5 -> 2, 3.5 -> 4, 34.5 -> 34).
 * JavaScript's Math.round sends every tie up (34.5 -> 35), which would put the Analysis tab one point above the stored score.
 * The backend is deliberately unchanged (no stored score moves); this mirrors it. */
export function roundHalfEven(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor; // exact for doubles in the score range
  if (diff < 0.5) return floor;
  if (diff > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Python 3.12's sum() of a list of floats: Neumaier compensated summation, not a plain left-to-right fold. The two differ in the
 * last bit for about a quarter of 4-term weighted blends, which is enough to move an exact-tie rounding. Mirrors CPython's
 * builtin_sum (float fast path); an empty list sums to 0. */
export function pySum(values: number[]): number {
  if (values.length === 0) return 0;
  let result = values[0];
  let compensation = 0;
  for (let i = 1; i < values.length; i++) {
    const x = values[i];
    const t = result + x;
    if (Math.abs(result) >= Math.abs(x)) compensation += result - t + x;
    else compensation += x - t + result;
    result = t;
  }
  return compensation !== 0 && Number.isFinite(compensation) ? result + compensation : result;
}
