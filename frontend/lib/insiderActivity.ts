import type { InsiderActivityOut, InsiderSentiment, InsiderTransaction } from "@/lib/api/types";
import { fmtCompactMoney } from "@/lib/format";

/** Which of the tab's three body states to render. `has_data` alone can't
 * tell "cached and genuinely empty" (HK/France/quiet tickers) apart from
 * "never successfully cached" (FMP paused, plan doesn't cover the endpoint,
 * or the fetch hasn't succeeded yet) -- `as_of` (the cached search row's
 * fetched_at) is what separates them, so the two must never be conflated. */
export type InsiderEmptyState = "content" | "empty" | "not_cached";

export function insiderViewState(data: Pick<InsiderActivityOut, "has_data" | "as_of">): InsiderEmptyState {
  if (data.has_data) return "content";
  return data.as_of ? "empty" : "not_cached";
}

export const SENTIMENT_LABELS: Record<InsiderSentiment, string> = {
  net_buying: "Net buying",
  net_selling: "Net selling",
  no_activity: "No activity",
  mixed: "Mixed",
};

// Green/red for a directional read, muted for everything else -- the same
// positive/negative tokens the rest of the app already uses (no new colors).
export const SENTIMENT_STYLES: Record<InsiderSentiment, string> = {
  net_buying: "bg-positive/16 text-positive border-positive/40",
  net_selling: "bg-negative/16 text-negative border-negative/40",
  no_activity: "bg-surface-2 text-text-tertiary border-border-card",
  mixed: "bg-surface-2 text-text-tertiary border-border-card",
};

/** Open-market-only (the default) keeps just buys and sales -- the
 * transactions that reflect an insider's own conviction, as opposed to
 * grants, exercises, gifts and tax withholding. */
export function filterInsiderTransactions(transactions: InsiderTransaction[], showAllTypes: boolean): InsiderTransaction[] {
  if (showAllTypes) return transactions;
  return transactions.filter((t) => t.kind === "open_market_buy" || t.kind === "open_market_sale");
}

/** "$1.23M", or "no cash value" for a $0 award/gift/exercise -- never "$0". */
export function fmtInsiderValue(t: Pick<InsiderTransaction, "has_cash_value" | "dollar_value">): string {
  if (!t.has_cash_value || t.dollar_value == null) return "no cash value";
  return fmtCompactMoney(t.dollar_value);
}

/** FMP's typeOfOwner is free text like "officer: Chief Executive Officer" or
 * "director" -- drop the "officer: " prefix and sentence-case it. */
export function fmtInsiderRole(role: string | null): string | null {
  if (!role) return null;
  const stripped = role.replace(/^officer:\s*/i, "").trim();
  if (!stripped) return null;
  return stripped.charAt(0).toUpperCase() + stripped.slice(1);
}

export function quarterLabel(year: number, quarter: number): string {
  return `${year} Q${quarter}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "YYYY-MM-DD" -> "Sep 1, 2026", parsed by hand: `new Date("2026-09-01")`
 * is UTC midnight, which renders as Aug 31 in any timezone west of UTC. */
export function fmtIsoDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** Timestamp -> local "Sep 19, 2026" (mirrors SentimentOverTimeCard's own as-of formatting). */
export function fmtAsOf(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
