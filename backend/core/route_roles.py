"""The one registry of who may call which route (docs/specs/auth.md). Every route of the app is listed here with a role:

* ``public``  -- no session needed. Only ``GET /api/health`` (start.sh polls it) and ``POST /api/auth/login``.
* ``viewer``  -- any signed-in user, admin or viewer. Reads, plus the two pure/own-session writes in VIEWER_ALLOWED_WRITES.
* ``admin``   -- admins only (403 for a viewer): every other write, and the reads that spend FMP/SEC calls or show operational detail.

`core/auth.py::authorize` (the app-level dependency) looks the request's route up here; a route that is missing is treated as admin-only,
and `tests/test_route_roles_registry.py` fails if a route is missing, a stale entry remains, a write method is registered ``viewer``
without being in VIEWER_ALLOWED_WRITES, or a ``{ticker}`` route does not carry the ticker guard (core/main.py::TickerPath), which is
what keeps a viewer on tracked tickers and cache-only reads. Adding a route means adding one line here."""

from typing import Literal

Role = Literal["public", "viewer", "admin"]
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Writes a viewer may make: signing out (their own session) and the pure Manual Calculation (no I/O, nothing stored).
VIEWER_ALLOWED_WRITES = frozenset({("POST", "/api/auth/logout"), ("POST", "/api/tickers/{ticker}/step3/manual")})

ROUTE_ROLES: dict[tuple[str, str], Role] = {
    ("POST", "/api/auth/login"): "public",
    ("GET", "/api/auth/me"): "viewer",
    ("POST", "/api/auth/logout"): "viewer",
    ("GET", "/api/health"): "public",
    # --- viewer
    ("GET", "/api/config/moat"): "viewer",
    ("GET", "/api/config/score-weights"): "viewer",
    ("GET", "/api/etf-screener"): "viewer",
    ("GET", "/api/etf-screener/meta"): "viewer",
    ("GET", "/api/market-breadth"): "viewer",
    ("GET", "/api/momentum"): "viewer",
    ("GET", "/api/momentum/etf"): "viewer",
    ("GET", "/api/opportunities/dates"): "viewer",
    ("GET", "/api/opportunities/latest"): "viewer",
    ("GET", "/api/opportunities/scorecard"): "viewer",
    ("GET", "/api/opportunities/scorecard/flags"): "viewer",
    ("GET", "/api/opportunities/scorecard/outcomes"): "viewer",
    ("GET", "/api/opportunities/scorecard/picks"): "viewer",
    ("GET", "/api/opportunities/{as_of_date}"): "viewer",
    ("GET", "/api/screener"): "viewer",
    ("GET", "/api/screener/filters"): "viewer",
    ("GET", "/api/screener/meta"): "viewer",
    ("GET", "/api/sector-heatmap"): "viewer",
    ("GET", "/api/technical-ideas/warren"): "viewer",
    ("GET", "/api/tickers/search"): "viewer",
    ("GET", "/api/tickers/{ticker}/analyst-ratings"): "viewer",
    ("GET", "/api/tickers/{ticker}/bank-capital-metrics"): "viewer",
    ("GET", "/api/tickers/{ticker}/chart"): "viewer",
    ("GET", "/api/tickers/{ticker}/custom-valuation"): "viewer",
    ("GET", "/api/tickers/{ticker}/entry-signal"): "viewer",
    ("GET", "/api/tickers/{ticker}/etf-overview"): "viewer",
    ("GET", "/api/tickers/{ticker}/financials"): "viewer",
    ("GET", "/api/tickers/{ticker}/liquidity-zones"): "viewer",
    ("GET", "/api/tickers/{ticker}/moat"): "viewer",
    ("GET", "/api/tickers/{ticker}/moat-check"): "viewer",
    ("GET", "/api/tickers/{ticker}/pe-history"): "viewer",
    ("GET", "/api/tickers/{ticker}/ratios"): "viewer",
    ("GET", "/api/tickers/{ticker}/score"): "viewer",
    ("GET", "/api/tickers/{ticker}/segmentation"): "viewer",
    ("GET", "/api/tickers/{ticker}/speculative-growth"): "viewer",
    ("GET", "/api/tickers/{ticker}/step1"): "viewer",
    ("GET", "/api/tickers/{ticker}/step2"): "viewer",
    ("GET", "/api/tickers/{ticker}/step3"): "viewer",
    ("POST", "/api/tickers/{ticker}/step3/manual"): "viewer",
    ("GET", "/api/tickers/{ticker}/step4"): "viewer",
    ("GET", "/api/tickers/{ticker}/step5"): "viewer",
    ("GET", "/api/tickers/{ticker}/summary"): "viewer",
    ("GET", "/api/tickers/{ticker}/trend-analysis"): "viewer",
    ("GET", "/api/tickers/{ticker}/universe"): "viewer",
    ("GET", "/api/watchlists"): "viewer",
    ("GET", "/api/watchlists/export-data"): "viewer",
    ("GET", "/api/watchlists/{watchlist_id}/etf-rows"): "viewer",
    ("GET", "/api/watchlists/{watchlist_id}/export/thinkorswim"): "viewer",
    ("GET", "/api/watchlists/{watchlist_id}/rows"): "viewer",
    # --- admin
    ("DELETE", "/api/technical-ideas/warren/{ticker}"): "admin",
    ("GET", "/api/config/cron-health"): "admin",
    ("GET", "/api/config/data-groups"): "admin",
    ("PUT", "/api/config/data-groups/master"): "admin",
    ("PUT", "/api/config/data-groups/plan"): "admin",
    ("PUT", "/api/config/data-groups/{group}"): "admin",
    ("POST", "/api/config/data-groups/{group}/retest"): "admin",
    ("DELETE", "/api/config/data-groups/{group}/variants"): "admin",
    ("GET", "/api/config/data-source-health"): "admin",
    # Read only by the Settings page, which a viewer cannot open (2026-10-14). The config reads other pages use (moat, score-weights) stay viewer.
    ("GET", "/api/config/discount-rate"): "admin",
    ("GET", "/api/config/discount-rates"): "admin",
    ("GET", "/api/config/liquidity-zones"): "admin",
    ("GET", "/api/config/reit-dividend-yield"): "admin",
    ("GET", "/api/config/weinstein"): "admin",
    ("PUT", "/api/config/discount-rate"): "admin",
    ("PUT", "/api/config/liquidity-zones"): "admin",
    ("PUT", "/api/config/moat"): "admin",
    ("PUT", "/api/config/reit-dividend-yield"): "admin",
    ("PUT", "/api/config/score-weights"): "admin",
    ("POST", "/api/config/score-weights/reset"): "admin",
    ("PUT", "/api/config/weinstein"): "admin",
    ("DELETE", "/api/screener/filters/{name}"): "admin",
    ("PUT", "/api/screener/filters/{name}"): "admin",
    ("POST", "/api/screener/recompute"): "admin",
    ("PUT", "/api/tickers/{ticker}/bank-capital-metrics"): "admin",
    ("DELETE", "/api/tickers/{ticker}/custom-valuation"): "admin",
    ("PUT", "/api/tickers/{ticker}/custom-valuation"): "admin",
    ("POST", "/api/tickers/{ticker}/custom-valuation/activate"): "admin",
    ("POST", "/api/tickers/{ticker}/custom-valuation/deactivate"): "admin",
    ("POST", "/api/tickers/{ticker}/etf-watchlist"): "admin",
    ("GET", "/api/tickers/{ticker}/financials/cash-flow-cell-check"): "admin",
    ("PUT", "/api/tickers/{ticker}/moat"): "admin",
    ("POST", "/api/tickers/{ticker}/refresh"): "admin",
    ("DELETE", "/api/tickers/{ticker}/universe"): "admin",
    ("POST", "/api/tickers/{ticker}/universe"): "admin",
    ("POST", "/api/watchlists"): "admin",
    ("DELETE", "/api/watchlists/{watchlist_id}"): "admin",
    ("PUT", "/api/watchlists/{watchlist_id}"): "admin",
    ("POST", "/api/watchlists/{watchlist_id}/tickers"): "admin",
    ("POST", "/api/watchlists/{watchlist_id}/tickers/bulk"): "admin",
    ("DELETE", "/api/watchlists/{watchlist_id}/tickers/{ticker}"): "admin",
}


def role_for(method: str, path: str | None) -> Role:
    """The role a route needs; admin when the route is unknown (fail closed)."""
    return ROUTE_ROLES.get((method.upper(), path or ""), "admin")
