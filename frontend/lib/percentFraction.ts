// Converting between a stored FRACTION (0.03608) and the PERCENT text a
// Settings field shows and takes (3.608), without letting binary-float noise
// leak in either direction. 12 significant digits is far more than any rate
// is ever entered with and far less than a double carries, so it strips noise
// (0.03608 * 100 is 3.6079999999999997; 0.02728 / 100 is not always 0.02728)
// without rounding any real digit.

/** A stored fraction as percent text at full precision: 0.02728 -> "2.728",
 * 0.036085 -> "3.6085". Never rounds to a fixed number of decimals. */
export function fractionToPercentText(fraction: number): string {
  const percent = Number((fraction * 100).toPrecision(12));
  const text = String(percent);
  // String() switches to exponent form for very small/large numbers, which the
  // number field (rightly) does not accept as typed input.
  return text.includes("e") ? percent.toFixed(12).replace(/0+$/, "").replace(/\.$/, "") : text;
}

/** A percent number as the fraction to store: 3.608 -> exactly 0.03608 (the
 * double nearest that decimal, as if it had been typed as 0.03608). */
export function percentToFraction(percent: number): number {
  return Number((percent / 100).toPrecision(12));
}
