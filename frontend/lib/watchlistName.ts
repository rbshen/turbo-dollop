// Mirrors the backend's WatchlistName constraint (WatchlistName in
// backend/core/schemas.py: whitespace stripped, then 1 to 100 characters).
// Kept in sync by hand -- there is no shared schema source between the two.
// Shared by the Watchlist name editor and AddToWatchlistButton's naming step.
export const WATCHLIST_NAME_MAX_LENGTH = 100;
