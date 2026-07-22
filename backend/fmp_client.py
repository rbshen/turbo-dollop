import asyncio
import logging
import time

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Investigation (see project history) found the empirical rate limit sits
# somewhere around 300-600 requests/minute on a rolling window, recovering
# roughly 65-70s after a 429. A couple of bounded retries at that recovery
# interval is a safety net for occasional hits -- proactive pacing (below)
# is the primary defense, not this.
RATE_LIMIT_MAX_RETRIES = 2
RATE_LIMIT_RETRY_BACKOFF_SECONDS = 65.0


class FMPClient:
    """Thin wrapper around the Financial Modeling Prep REST API.

    `min_request_interval` throttles real outbound HTTP calls (never cache
    hits, since those never reach this class) to a minimum gap between
    requests -- 0.0 (default) means no throttling, correct for the
    interactive app where traffic is naturally sparse. The nightly bulk
    fetch script raises it on this same module-level singleton before
    running, so pacing lives here once rather than being duplicated per
    caller.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None, min_request_interval: float = 0.0) -> None:
        self.base_url = base_url or settings.fmp_base_url
        self.api_key = api_key or settings.fmp_api_key
        self.min_request_interval = min_request_interval
        self.request_count = 0
        self._last_request_at: float | None = None
        self._pace_lock = asyncio.Lock()

    async def _pace(self) -> None:
        if self.min_request_interval <= 0:
            return
        async with self._pace_lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                wait = self.min_request_interval - (now - self._last_request_at)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def get(self, endpoint: str, params: dict | None = None) -> dict | list:
        query = {**(params or {}), "apikey": self.api_key}
        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            await self._pace()
            self.request_count += 1
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                response = await client.get(endpoint, params=query)
            if response.status_code == 429 and attempt < RATE_LIMIT_MAX_RETRIES:
                logger.warning(
                    "FMP 429 rate limit hit for %s (attempt %d/%d), backing off %.0fs",
                    endpoint,
                    attempt + 1,
                    RATE_LIMIT_MAX_RETRIES,
                    RATE_LIMIT_RETRY_BACKOFF_SECONDS,
                )
                await asyncio.sleep(RATE_LIMIT_RETRY_BACKOFF_SECONDS)
                continue
            response.raise_for_status()
            return response.json()
        raise AssertionError("unreachable")  # loop always returns or raises above

    async def get_profile(self, ticker: str) -> dict | list:
        return await self.get("/profile", {"symbol": ticker})

    async def get_quote(self, ticker: str) -> dict | list:
        return await self.get("/quote", {"symbol": ticker})

    async def get_price_change(self, ticker: str) -> dict | list:
        return await self.get("/stock-price-change", {"symbol": ticker})

    async def get_analyst_estimates(self, ticker: str) -> dict | list:
        return await self.get("/analyst-estimates", {"symbol": ticker, "period": "annual", "limit": 10})

    async def get_ratios(self, ticker: str, period: str = "annual", limit: int = 1) -> dict | list:
        return await self.get("/ratios", {"symbol": ticker, "period": period, "limit": limit})

    async def get_treasury_rates(self, from_date: str, to_date: str) -> dict | list:
        return await self.get("/treasury-rates", {"from": from_date, "to": to_date})

    async def get_earnings(self, ticker: str) -> dict | list:
        return await self.get("/earnings", {"symbol": ticker, "limit": 8})

    async def get_income_statement(self, ticker: str, period: str, limit: int) -> dict | list:
        return await self.get("/income-statement", {"symbol": ticker, "period": period, "limit": limit})

    async def get_cash_flow_statement(self, ticker: str, period: str, limit: int) -> dict | list:
        return await self.get("/cash-flow-statement", {"symbol": ticker, "period": period, "limit": limit})

    async def get_balance_sheet_statement(self, ticker: str, period: str, limit: int) -> dict | list:
        return await self.get("/balance-sheet-statement", {"symbol": ticker, "period": period, "limit": limit})

    async def get_key_metrics(self, ticker: str, period: str, limit: int) -> dict | list:
        return await self.get("/key-metrics", {"symbol": ticker, "period": period, "limit": limit})

    async def get_key_metrics_ttm(self, ticker: str) -> dict | list:
        return await self.get("/key-metrics-ttm", {"symbol": ticker})

    async def get_financial_statement_full_as_reported(self, ticker: str, period: str, limit: int) -> dict | list:
        # Raw SEC-XBRL-tag dump, NOT the standardized schema the other
        # methods above use -- field names are the filer's own XBRL tags, so
        # they are not guaranteed consistent across companies (see
        # npl.py::compute_npl_ratio for how this is handled defensively).
        return await self.get(
            "/financial-statement-full-as-reported", {"symbol": ticker, "period": period, "limit": limit}
        )


fmp_client = FMPClient()
