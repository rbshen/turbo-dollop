// Pure parsing, validation and stepping for NumberField. Nothing here ever
// clamps, rounds or snaps what the user typed: an invalid value yields an
// error message, never a corrected value.

/** Suffix letters and their multipliers, e.g. `{ M: 1e6, B: 1e9, T: 1e12 }`.
 * Matched case-insensitively. */
export type NumberSuffixes = Record<string, number>;

export interface NumberRules {
  integer?: boolean;
  min?: number;
  max?: number;
  /** An empty field is valid and reads as null (no value), not an error. */
  optional?: boolean;
  /** Allow a trailing suffix ("500M", "2 b", "1.5T"); the result is in base
   * units. Without this, any letter makes the text invalid. */
  suffixes?: NumberSuffixes;
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

// The same number shapes, then an optional run of letters (and spaces) for a
// suffix: "500M", "2 b", "1.5T", ".5B", "12.B". The letters are looked up in
// `suffixes`; an unknown one ("1x", "5e", "1BX") is invalid.
const NUMBER_WITH_SUFFIX_TEXT = /^(-?(?:\d+\.?\d*|\.\d+))\s*([A-Za-z]*)$/;

function parseNumberText(trimmed: string, suffixes?: NumberSuffixes): number | null {
  if (!suffixes) return NUMBER_TEXT.test(trimmed) ? Number(trimmed) : null;
  const match = NUMBER_WITH_SUFFIX_TEXT.exec(trimmed);
  if (!match) return null;
  const [, numberPart, suffixPart] = match;
  if (suffixPart === "") return Number(numberPart);
  const wanted = suffixPart.toUpperCase();
  const key = Object.keys(suffixes).find((k) => k.toUpperCase() === wanted);
  return key === undefined ? null : Number(numberPart) * suffixes[key];
}

/** "-", "." and "-." are the prefixes of a number that is not yet one. A
 * field that is still being typed in should hold its previous value and show
 * no error for them; once it loses focus they are just invalid text. */
export function isIncompleteNumberPrefix(text: string): boolean {
  return /^(-|\.|-\.)$/.test(text.trim());
}

export function checkNumber(text: string, rules: NumberRules = {}): NumberCheck {
  const trimmed = text.trim();
  if (trimmed === "" && rules.optional) return { value: null, error: null };
  const parsed = parseNumberText(trimmed, rules.suffixes);
  if (parsed === null) return { value: null, error: "Enter a number." };
  const value = parsed;
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

/** The text a stored number reads back as in a box: "" for null, plain
 * digits without `suffixes`. With them, the SHORTEST exact form: 1e9 -> "1B",
 * 1.5e9 -> "1.5B", 2.5e12 -> "2.5T", 1234567 -> "1234567". A candidate counts
 * only if parsing it returns exactly the same number; otherwise a smaller
 * suffix is tried, and finally the plain digits. Ties go to the suffix. */
export function formatNumberInput(value: number | null, suffixes?: NumberSuffixes): string {
  if (value === null) return "";
  const plain = Math.abs(value) >= 1e21 ? value.toFixed(0) : String(value);
  if (!suffixes || value <= 0) return plain;
  let best = plain;
  const ordered = Object.entries(suffixes).sort((a, b) => b[1] - a[1]);
  for (const [suffix, multiplier] of ordered) {
    if (value < multiplier) continue;
    const candidate = `${value / multiplier}${suffix}`;
    if (candidate.length > best.length) continue;
    if (candidate.length === best.length && best !== plain) continue;
    if (parseNumberText(candidate, suffixes) === value) best = candidate;
  }
  return best;
}
