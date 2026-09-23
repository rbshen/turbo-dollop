"""Thin wrapper around Massive.com's REST API (a Polygon.io rebrand -- same
request shape, confirmed live in
docs/massive_feasibility_investigation_2026-09-23.md). Mirrors
clients/fmp_client.py's shape (thin client class + module-level singleton,
retry/backoff on 429, record_success on every real call) -- see that
module for the precedent this follows.

Massive/Polygon is the daily-bar price-data provider for every US-listed
daily-bar consumer (see clients/daily_bar_sources.py), replacing Yahoo
Finance there. Yahoo stays wired in for non-US tickers and as a
per-ticker/per-batch fallback (see clients/daily_bar_sources.py) -- this
client itself has no fallback logic of its own, that lives one layer up.

Every method here is per-ticker-tolerant the same way
clients/yahoo_client.py::YahooClient.get_history is: a symbol Massive has
no data for (bad/delisted/not-yet-listed) returns an empty result, never
raises. A genuine transport/HTTP error (after the retries below are
exhausted) DOES raise -- the caller (clients/daily_bar_sources.py) is what
turns that into a per-ticker Yahoo fallback, not this module."""

import asyncio
import logging
from datetime import date

import httpx
import pandas as pd

from core.config import settings
from core.data_source_health import record_success

logger = logging.getLogger(__name__)

# Massive/Polygon's own OHLCV field names on every /v2/aggs-family
# endpoint (both per-ticker range and grouped-daily): t=start timestamp
# (Unix ms, UTC), o/h/l/c=open/high/low/close, v=volume. Grouped-daily
# additionally carries the ticker symbol itself under "T" (capital, to
# avoid colliding with "t").
_BAR_COLUMNS = ["t", "o", "h", "l", "c", "v"]

# Confirmed live (feasibility investigation §Part 1b): 300 sequential
# requests at natural ~0.67s/req pacing produced zero 429s on Starter --
# this retry exists as cheap insurance for an occasional hit, not because
# it was observed necessary, mirroring FMPClient's own reasoning for its
# retry constants.
RATE_LIMIT_MAX_RETRIES = 2
RATE_LIMIT_RETRY_BACKOFF_SECONDS = 15.0
SERVER_ERROR_MAX_RETRIES = 2
SERVER_ERROR_RETRY_BACKOFF_SECONDS = 5.0


def _bars_to_frame(results: list[dict]) -> pd.DataFrame:
    """Massive's raw `results` rows -> a lowercase-column OHLCV DataFrame
    with a naive DatetimeIndex at midnight of the trading day -- the exact
    shape clients/shared_bars_cache.py::_write_rows already expects, so no
    adapter is needed at any daily_bar_sources.py call site.

    `t` is a Unix-ms UTC timestamp of the start of the aggregate window;
    converting through America/New_York and normalizing (rather than
    trusting the raw UTC date, which can be off by a day depending on
    exactly which UTC hour Polygon anchors daily bars to) reliably recovers
    the real trading date regardless of that anchoring convention."""
    if not results:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame.from_records(results)
    missing = [c for c in _BAR_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Massive bar response missing expected column(s): {missing}")
    index = (
        pd.to_datetime(df["t"], unit="ms", utc=True)
        .dt.tz_convert("America/New_York")
        .dt.normalize()
        .dt.tz_localize(None)
    )
    # Built from .to_numpy() arrays, not the raw Series objects, and
    # deliberately not passed `index=` at construction time -- pandas
    # aligns a dict-of-Series DataFrame constructor's values against the
    # supplied index BY LABEL, and df["o"]/etc.'s own default RangeIndex
    # (0, 1, 2, ...) shares no labels with the DatetimeIndex built above,
    # which silently produced an all-NaN frame the first time this was
    # written (caught by this module's own tests, not assumed correct).
    out = pd.DataFrame(
        {
            "open": df["o"].to_numpy(dtype=float),
            "high": df["h"].to_numpy(dtype=float),
            "low": df["l"].to_numpy(dtype=float),
            "close": df["c"].to_numpy(dtype=float),
            "volume": df["v"].fillna(0).to_numpy(dtype="int64"),
        }
    )
    out.index = pd.DatetimeIndex(index.to_numpy(), name="bar_time")
    return out.sort_index()


class MassiveClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = base_url or settings.massive_base_url
        self.api_key = api_key or settings.massive_api_key

    async def _get(self, url: str, params: dict | None = None, *, absolute: bool = False) -> dict:
        """One HTTP GET with the standard retry policy. `absolute=True`
        skips the base_url join -- used when following a `next_url` cursor,
        which already comes back as a complete URL (scheme/host/path/query
        all included, EXCEPT the API key -- confirmed live, Massive's
        `next_url` cursor carries every other original query param verbatim
        but not `apiKey`, so it's re-added here via `params`, which httpx
        merges with a URL's own existing query string rather than
        replacing it)."""
        query = {**(params or {}), "apiKey": self.api_key}
        for attempt in range(max(RATE_LIMIT_MAX_RETRIES, SERVER_ERROR_MAX_RETRIES) + 1):
            async with httpx.AsyncClient(base_url="" if absolute else self.base_url, timeout=30.0) as client:
                response = await client.get(url, params=query)
            if response.status_code == 429 and attempt < RATE_LIMIT_MAX_RETRIES:
                logger.warning("Massive 429 rate limit for %s (attempt %d), backing off %.0fs",
                                url, attempt + 1, RATE_LIMIT_RETRY_BACKOFF_SECONDS)
                await asyncio.sleep(RATE_LIMIT_RETRY_BACKOFF_SECONDS)
                continue
            if response.status_code >= 500 and attempt < SERVER_ERROR_MAX_RETRIES:
                logger.warning("Massive %d for %s (attempt %d), backing off %.0fs",
                                response.status_code, url, attempt + 1, SERVER_ERROR_RETRY_BACKOFF_SECONDS)
                await asyncio.sleep(SERVER_ERROR_RETRY_BACKOFF_SECONDS)
                continue
            response.raise_for_status()
            record_success("massive")
            return response.json()
        raise AssertionError("unreachable")  # loop always returns or raises above

    async def _paginate(self, first_url: str, params: dict) -> list[dict]:
        """Follows `next_url` until exhausted, accumulating every page's
        `results` -- never reads page 1 only. Confirmed in the feasibility
        investigation that daily-granularity requests don't paginate in
        practice within a 5y window, but the loop exists regardless: it's
        the one thing every call site of this module must never skip."""
        results: list[dict] = []
        body = await self._get(first_url, params)
        results.extend(body.get("results") or [])
        next_url = body.get("next_url")
        while next_url:
            body = await self._get(next_url, absolute=True)
            results.extend(body.get("results") or [])
            next_url = body.get("next_url")
        return results

    async def get_daily_bars(self, ticker: str, start: date, end: date, adjusted: bool = False) -> pd.DataFrame:
        """One ticker's daily OHLCV bars over [start, end] (inclusive).
        Empty frame (never raises) for a symbol Massive has no data for."""
        url = f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}"
        try:
            results = await self._paginate(url, {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            raise
        return _bars_to_frame(results)

    async def get_grouped_daily(self, day: date, adjusted: bool = False) -> dict[str, pd.DataFrame]:
        """Whole US market, one call -- {Massive ticker symbol: one-row
        OHLCV DataFrame}. Callers translate symbols back to Fathom's
        canonical form via core/tickers.py::from_massive_symbol."""
        url = f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}"
        body = await self._get(url, {"adjusted": str(adjusted).lower()})
        rows = body.get("results") or []
        out: dict[str, pd.DataFrame] = {}
        for row in rows:
            symbol = row.get("T")
            if not symbol:
                continue
            frame = _bars_to_frame([row])
            if not frame.empty:
                out[symbol] = frame
        return out

    async def get_recent_splits(self, since: date) -> list[dict]:
        """Every split across the whole US market with execution_date >=
        `since`, one ticker per result row (`ticker`, `execution_date`,
        `split_from`, `split_to`). No `ticker` filter -- see
        clients/daily_bar_sources.py for how this is used to force a full
        refetch for any affected ticker in that night's batch, without a
        per-ticker splits check."""
        results = await self._paginate(
            "/v3/reference/splits", {"execution_date.gte": since.isoformat(), "order": "asc", "limit": 1000}
        )
        return results

    async def get_snapshot(self, ticker: str) -> dict | None:
        """Single-ticker snapshot (`day`/`min`/`prevDay`/`lastTrade`/
        `lastQuote`) -- for the ticker-page price/quote fallback. None for
        a symbol Massive has no snapshot for, never raises on a 404."""
        url = f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
        try:
            body = await self._get(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return body.get("ticker")


massive_client = MassiveClient()
