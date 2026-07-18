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

/** "+1.23%" / "-1.23%" / "0.00%"; expects a value already in percentage points (e.g. 11.98 for 11.98%). */
export function fmtPct(n: number, decimals = 2): string {
  const threshold = 0.5 * Math.pow(10, -decimals);
  if (Math.abs(n) < threshold) return (0).toFixed(decimals) + "%";
  return (n >= 0 ? "+" : "") + n.toFixed(decimals) + "%";
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
