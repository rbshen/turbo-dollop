// The nightly technical jobs (Liquidity Zones, BB+RSI, Warren) only run for tickers on a
// "monitored" watchlist: one named E<number> (E1, E2, ... E10, no upper limit) or exactly
// "ETF". The rule itself lives in the backend (backend/data/watchlists.py,
// MONITORED_WATCHLIST_PATTERN); the frontend never matches names, it only describes the rule,
// from this one place.
export const MONITORED_WATCHLISTS_PHRASE = 'a watchlist named E<number> (E1, E2, ...) or "ETF"';
