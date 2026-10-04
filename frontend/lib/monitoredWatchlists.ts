// The nightly technical jobs (Liquidity Zones, BB+RSI, Warren) only run for tickers on a
// "monitored" watchlist: one named E<number> (E1, E2, ... E10, no upper limit) or exactly
// "ETF". The rule itself lives in the backend (backend/data/watchlists.py,
// MONITORED_WATCHLIST_PATTERN) and reaches the frontend as WatchlistOut.monitored; the frontend
// never matches names, it only describes the rule, from this one place.
export const MONITORED_WATCHLISTS_PHRASE = 'a watchlist named E<number> (E1, E2, ...) or "ETF"';

// The list the ETF page's "Add to watchlist" button adds to (backend ETF_WATCHLIST_NAME).
export const ETF_WATCHLIST_NAME = "ETF";

/** Who a watchlist menu or filter is for. The list named "ETF" holds ETFs only (the backend refuses a stock), so
 * stock-facing UI hides it and ETF-facing UI shows every list. */
export type WatchlistAudience = "stock" | "etf";

/** The lists a menu or filter for `audience` offers: everything for "etf", everything but the "ETF" list for "stock". */
export function listsForAudience<T extends { name: string }>(watchlists: T[], audience: WatchlistAudience): T[] {
  return audience === "etf" ? watchlists : watchlists.filter((w) => w.name !== ETF_WATCHLIST_NAME);
}

/** Any spelling of the reserved name ("etf", " ETF "): the backend refuses to create or rename a list to it, and the
 * "New watchlist" box blocks it before the request. */
export function isReservedEtfListName(name: string): boolean {
  return name.trim().toLowerCase() === ETF_WATCHLIST_NAME.toLowerCase();
}

/** The empty-state sentence of a Technical card whose nightly job has no row for this ticker.
 * `check` is the card's own name ("BB+RSI entry signal"). An ETF is pointed at the ETF list. */
export function notTrackedMessage(check: string, isEtf = false): string {
  if (isEtf) {
    return `No ${check} tracked for this ETF -- this check only runs nightly for ETFs on the "${ETF_WATCHLIST_NAME}" watchlist (or ${MONITORED_WATCHLISTS_PHRASE}). Add it with Add to watchlist; it is picked up on the next nightly run.`;
  }
  return `No ${check} tracked for this ticker -- this check only runs nightly for tickers on ${MONITORED_WATCHLISTS_PHRASE}.`;
}
