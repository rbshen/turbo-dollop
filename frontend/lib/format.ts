function absLocale(n: number, decimals: number): string {
  return Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** "+" / "-" / "" for use as a sign prefix; values within +/-0.005 are display-zero. */
export function signChar(n: number): string {
  if (Math.abs(n) < 0.005) return "";
  return n >= 0 ? "+" : "-";
}

/** "$1,234.56" / "-$1,234.56" */
export function fmtMoney(n: number): string {
  return (n < 0 ? "-" : "") + "$" + absLocale(n, 2);
}

/** "+$1,234.56" / "-$1,234.56" / "$0.00" */
export function fmtSignedMoney(n: number): string {
  return signChar(n) + "$" + absLocale(n, 2);
}

/** "$4.90T" / "$482.11B" / "$12.50M" for large magnitudes, falls back to fmtMoney below $1M. */
export function fmtCompactMoney(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return fmtMoney(n);
}

/** "#,###.00M" — table format for raw dollar figures (e.g. 416161000000 -> "416,161.00M"). */
export function fmtTableMoney(n: number): string {
  return (n / 1_000_000).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "M";
}

/** "#,###.00" — like fmtTableMoney but without the "M" suffix, for tables
 * that already state their unit once (e.g. a "figures in USD millions"
 * note) instead of repeating it on every cell. */
export function fmtTableNumber(n: number): string {
  return (n / 1_000_000).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** "+1.23%" / "-1.23%" / "0.00%"; expects a value already in percentage points (e.g. 11.98 for 11.98%). */
export function fmtPct(n: number, decimals = 2): string {
  const threshold = 0.5 * Math.pow(10, -decimals);
  if (Math.abs(n) < threshold) return (0).toFixed(decimals) + "%";
  return (n >= 0 ? "+" : "") + n.toFixed(decimals) + "%";
}

export interface AxisMoneyUnit {
  divisor: number;
  suffix: string;
}

/** Picks one consistent compact unit (k/M/B/T) for a whole chart axis based on
 * its max value, per the mockup's "$Xk"-style compact tick format generalized
 * across magnitudes — so a large-cap ticker's axis reads "$400B" instead of
 * an absurd "$400,000,000k". */
export function pickAxisMoneyUnit(maxAbs: number): AxisMoneyUnit {
  if (maxAbs >= 1e12) return { divisor: 1e12, suffix: "T" };
  if (maxAbs >= 1e9) return { divisor: 1e9, suffix: "B" };
  if (maxAbs >= 1e6) return { divisor: 1e6, suffix: "M" };
  if (maxAbs >= 1e3) return { divisor: 1e3, suffix: "k" };
  return { divisor: 1, suffix: "" };
}

export function fmtAxisMoney(n: number, unit: AxisMoneyUnit): string {
  return `$${(n / unit.divisor).toFixed(0)}${unit.suffix}`;
}

/** Plain number, fixed decimals (e.g. beta, P/E). */
export function fmtNumber(n: number, decimals = 2): string {
  return n.toFixed(decimals);
}

/** Tailwind text class based on sign; near-zero is muted. */
export function pnlClass(n: number): string {
  if (n > 0.005) return "text-emerald-400";
  if (n < -0.005) return "text-red-400";
  return "text-zinc-500";
}

/** Same palette for underlying price/index changes. */
export const changeClass = pnlClass;
