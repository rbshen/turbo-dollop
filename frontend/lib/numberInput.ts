// Pure parsing, validation and stepping for NumberField. Nothing here ever
// clamps, rounds or snaps what the user typed: an invalid value yields an
// error message, never a corrected value.

export interface NumberRules {
  integer?: boolean;
  min?: number;
  max?: number;
}

export interface NumberCheck {
  /** The parsed number, or null when the text is not a number at all. */
  value: number | null;
  /** A plain-English error, or null when the text is a valid value. */
  error: string | null;
}

// Optional minus, digits with an optional fraction ("12", "12.", "12.5",
// ".5"). No plus sign, exponent, thousands separator or comma decimal.
const NUMBER_TEXT = /^-?(\d+\.?\d*|\.\d+)$/;

export function checkNumber(text: string, rules: NumberRules = {}): NumberCheck {
  const trimmed = text.trim();
  if (!NUMBER_TEXT.test(trimmed)) return { value: null, error: "Enter a number." };
  const value = Number(trimmed);
  if (rules.integer && !Number.isInteger(value)) return { value, error: "Enter a whole number." };
  const { min, max } = rules;
  if (min !== undefined && max !== undefined && (value < min || value > max)) {
    return { value, error: `Enter a value between ${min} and ${max}.` };
  }
  if (min !== undefined && value < min) return { value, error: `Enter a value of at least ${min}.` };
  if (max !== undefined && value > max) return { value, error: `Enter a value of at most ${max}.` };
  return { value, error: null };
}

function decimalPlaces(n: number): number {
  const [mantissa, exponent] = n.toString().split("e");
  const fraction = mantissa.split(".")[1]?.length ?? 0;
  return Math.max(0, fraction - (exponent ? Number(exponent) : 0));
}

/** One keyboard/button step from a VALID `current` value: +/- `step`
 * (ten times that when `big`), rounded to the precision of `current` and
 * `step` so 0.1 + 0.2 reads 0.3, and stopped at min/max. Stopping at a bound
 * is only ever the result of an explicit key press; typed text is never
 * touched. */
export function stepNumber(
  current: number,
  direction: 1 | -1,
  step: number,
  big: boolean,
  bounds: Pick<NumberRules, "min" | "max"> = {},
): number {
  const raw = current + direction * step * (big ? 10 : 1);
  const places = Math.max(decimalPlaces(current), decimalPlaces(step));
  let next = Number(raw.toFixed(places));
  if (bounds.min !== undefined) next = Math.max(bounds.min, next);
  if (bounds.max !== undefined) next = Math.min(bounds.max, next);
  return next;
}
