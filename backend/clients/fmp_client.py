import asyncio
import logging
import time

import httpx

from core.config import settings
from core.data_groups import (
    NON_US_CANARY_GROUPS,
    PROBE_ENDPOINTS,
    clear_restricted,
    describe_off,
    effective_state,
    get_snapshot,
    group_for_endpoint,
    mark_restricted,
    record_group_failure,
    record_group_success,
    set_key_problem,
)
from core.data_source_health import record_success

logger = logging.getLogger(__name__)

# Investigation (see project history) found the empirical rate limit sits
# somewhere around 300-600 requests/minute on a rolling window, recovering
# roughly 65-70s after a 429. A couple of bounded retries at that recovery
# interval is a safety net for occasional hits -- proactive pacing (below)
# is the primary defense, not this.
RATE_LIMIT_MAX_RETRIES = 2
RATE_LIMIT_RETRY_BACKOFF_SECONDS = 65.0


class FMPDisabledError(httpx.HTTPError):
    """Raised by FMPClient.get instead of attempting a network call when the
    endpoint's data group is not live -- subclasses httpx.HTTPError so every
    existing safe_fetch/except-httpx.HTTPError call site already treats
    this exactly like any other fetch failure, no changes needed there.
    core.cache's get_or_fetch/get_or_fetch_earnings_aware/force_fetch check
    the same per-group state directly (see their own comments) so a stale
    cached row is served instead of this ever needing to be caught in
    practice for those call sites -- this exists as the literal single
    choke point that guarantees zero network attempts regardless of
    caller."""


class FMPGroupDisabledError(FMPDisabledError):
    """The specific FMPDisabledError FMPClient.get raises for a group that
    is not live (master switch off, group disabled, required tier above the
    user's plan, or restricted by FMP) -- see core/data_groups.py.
    `group` names the data group so callers/logs can say which."""

    def __init__(self, message: str, group: str | None = None) -> None:
        super().__init__(message)
        self.group = group


_CANARY_SYMBOL = "AAPL"


def _canary_params(params: dict) -> dict | None:
    """The same request with the symbol swapped for AAPL, or None when
    there is nothing to swap (symbol-less endpoint, or already AAPL -- the
    failing call itself then IS the canary)."""
    for key in ("symbol", "symbols", "query"):
        if key in params:
            if str(params[key]).upper() == _CANARY_SYMBOL:
                return None
            return {**params, key: _CANARY_SYMBOL}
    return None


def _safe(fn, *args) -> None:
    """Bookkeeping writes must never mask the real fetch outcome."""
    try:
        fn(*args)
    except Exception:
        logger.warning("data-group bookkeeping failed (%s)", getattr(fn, "__name__", fn), exc_info=True)


def _clear_key_problem_if_set() -> None:
    if get_snapshot().key_problem_at is not None:
        _safe(set_key_problem, None)  # a successful call proves the key works


# FMP's three /price-target-* endpoints know Brown-Forman's class B shares only
# as "BF.B" -- "BF-B" returns an empty list there (confirmed live 2026-09-25),
# although /profile and /grades-consensus want the hyphen form. Deliberately a
# one-entry allowlist, not a blanket hyphen->dot replace: BRK-B answers under
# both spellings but with DIFFERENT data (604 vs 575), so remapping it would
# silently change its values, and BF-A only exists hyphenated.
PRICE_TARGET_SYMBOL_OVERRIDES = {"BF-B": "BF.B"}


def _price_target_symbol(ticker: str) -> str:
    return PRICE_TARGET_SYMBOL_OVERRIDES.get(ticker, ticker)


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

    async def get(self, endpoint: str, params: dict | None = None, group: str | None = None) -> dict | list:
        """`group` overrides the endpoint's default data group -- only for an
        endpoint that serves two features (see
        core.data_groups.ENDPOINT_GROUP_OVERRIDES_USED)."""
        group = group or group_for_endpoint(endpoint)
        if group is None:
            # Fail closed: an unmapped endpoint must never bypass the gate
            # (tests/test_data_groups_registry.py keeps this unreachable).
            raise FMPGroupDisabledError(f"no data group mapped for endpoint {endpoint}", group=None)
        live, _reason = effective_state(group)
        if not live:
            raise FMPGroupDisabledError(
                f"data group {group} is off ({describe_off(group)}) -- refusing live call to {endpoint}", group=group
            )
        query = {**(params or {}), "apikey": self.api_key}
        try:
            response = await self._send(endpoint, query)
        except httpx.HTTPError as exc:  # transport-level (timeout/connect): a failing group, never a restriction
            record_group_failure(group, type(exc).__name__)
            raise
        status = response.status_code
        if status < 400:
            record_success("fmp")
            record_group_success(group)
            _clear_key_problem_if_set()
            return response.json()
        if status in (401, 403):
            # A key problem, not a plan restriction: global warning, no group blamed.
            _safe(set_key_problem, f"HTTP {status} from {endpoint}")
        elif status == 402:
            await self._handle_plan_restriction(group, endpoint, params or {})
        elif status == 429:
            pass  # rate limit: never marks anything
        else:
            record_group_failure(group, f"HTTP {status}")
        response.raise_for_status()
        raise AssertionError("unreachable")  # status >= 400 always raises above

    async def _send(self, endpoint: str, query: dict) -> httpx.Response:
        """One paced request with the bounded 429 retry. Never raises for an
        HTTP error status -- the caller decides what each status means."""
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
            return response
        raise AssertionError("unreachable")  # loop always returns above

    async def _handle_plan_restriction(self, group: str, endpoint: str, params: dict) -> None:
        """A 402 can be symbol-scoped (e.g. a non-US symbol on a US-only
        plan), so the failing call alone never disables a group: probe a
        canary (AAPL, same endpoint) and mark the group plan_restricted only
        if the canary ALSO gets a 402. An endpoint with no symbol/query
        parameter has no canary to vary -- the failing call is its own
        canary."""
        if group in NON_US_CANARY_GROUPS:
            # A non-US group's own restriction (a plan without global coverage) is
            # symbol-scoped BY DEFINITION, so swapping in AAPL would always read
            # "symbol-scoped, left live". Its canary is another non-US symbol.
            canary = dict(PROBE_ENDPOINTS[group][1])
            if str(params["symbol"] if "symbol" in params else "").upper() == str(canary["symbol"]).upper():
                canary = None  # the failing call is already the canary
        else:
            canary = _canary_params(params)
        if canary is None:
            confirmed = True
        else:
            try:
                response = await self._send(endpoint, {**canary, "apikey": self.api_key})
                confirmed = response.status_code == 402
            except httpx.HTTPError:
                confirmed = False  # inconclusive -- never mark on a failed probe
        if confirmed:
            logger.warning("FMP 402 confirmed by canary for %s: marking group %s plan_restricted", endpoint, group)
            _safe(mark_restricted, group, f"HTTP 402 on {endpoint} (canary confirmed)")
        else:
            logger.warning("FMP 402 for %s was symbol-scoped (canary OK); group %s left live", endpoint, group)

    async def probe_group(self, group: str) -> str:
        """Re-probe one group with its canary endpoint (AAPL), bypassing the
        gate (a restricted group is gated off by definition). Returns
        "ok" (200: restriction cleared), "restricted" (402), or
        "inconclusive" (anything else -- state left untouched)."""
        target = PROBE_ENDPOINTS.get(group)
        if target is None:
            return "inconclusive"
        endpoint, params = target
        try:
            response = await self._send(endpoint, {**params, "apikey": self.api_key})
        except httpx.HTTPError:
            return "inconclusive"
        if response.status_code < 400:
            _safe(clear_restricted, group)
            return "ok"
        if response.status_code == 402:
            _safe(mark_restricted, group, f"HTTP 402 on {endpoint} (re-probe)")
            return "restricted"
        if response.status_code in (401, 403):
            _safe(set_key_problem, f"HTTP {response.status_code} from {endpoint} (re-probe)")
        return "inconclusive"

    async def reprobe_restricted_groups(self) -> dict[str, str]:
        """Re-probe every group currently plan_restricted (weekly, and when the
        user edits their plan). No-op while the master switch is off (zero
        live calls)."""
        snap = get_snapshot()
        if not snap.master_on:
            return {}
        return {
            g: await self.probe_group(g) for g, st in snap.groups.items() if st.status == "plan_restricted"
        }

    async def get_profile(self, ticker: str) -> dict | list:
        return await self.get("/profile", {"symbol": ticker})

    async def get_quote(self, ticker: str) -> dict | list:
        return await self.get("/quote", {"symbol": ticker})

    async def get_forex_quote(self, from_currency: str) -> dict | list:
        """Spot rate for `from_currency` -> USD, via the same `/quote`
        endpoint every stock ticker uses -- FMP serves forex pairs there
        too. Confirmed live: querying "<CCY>USD" (e.g. "TWDUSD", "EURUSD")
        always returns `price` as USD per 1 unit of `from_currency`
        directly, regardless of which side of the pair is conventionally
        quoted as the base in interbank FX (EUR/GBP-style pairs are
        normally quoted EUR-as-base against USD, unlike TWD/CAD/CNY/SGD/DKK)
        -- FMP supports both directions for every pair, so always picking
        the "<CCY>USD" direction avoids needing a per-currency lookup table
        for which side is "normal." Used by step3_data.py's non-USD
        reported-currency conversion; never called for a USD-reporting
        ticker."""
        return await self.get("/quote", {"symbol": f"{from_currency}USD"}, group="fundamentals")

    async def get_price_change(self, ticker: str) -> dict | list:
        return await self.get("/stock-price-change", {"symbol": ticker})

    async def get_analyst_estimates(self, ticker: str) -> dict | list:
        return await self.get("/analyst-estimates", {"symbol": ticker, "period": "annual", "limit": 10})

    async def get_ratios(self, ticker: str, period: str = "annual", limit: int = 1) -> dict | list:
        return await self.get("/ratios", {"symbol": ticker, "period": period, "limit": limit})

    async def get_earnings(self, ticker: str) -> dict | list:
        return await self.get("/earnings", {"symbol": ticker, "limit": 8})

    async def get_earnings_history(self, ticker: str, limit: int = 40) -> dict | list:
        # Deeper counterpart to get_earnings above (which only needs the next/latest
        # date, so stays at limit=8): one row per fiscal quarter, newest first,
        # including the next scheduled (not-yet-reported) date with null actuals --
        # see data/chart_events_data.py, the only consumer. 40 rows ~ 10 years,
        # comfortably past the Chart tab's widest (4y) window.
        return await self.get("/earnings", {"symbol": ticker, "limit": limit}, group="corporate_events")

    async def get_dividends(self, ticker: str, limit: int = 400) -> dict | list:
        # One row per declared dividend, newest first, INCLUDING declared-but-
        # not-yet-ex future dates. `date` is the ex-dividend date; `dividend` is
        # the as-declared amount, `adjDividend` the split-adjusted one (matches
        # the split-adjusted candles). Confirmed live that `from`/`to` are NOT
        # honored (the full history comes back regardless), so `limit` is the
        # only lever -- 400 covers the 4y Chart window even for a weekly payer.
        return await self.get("/dividends", {"symbol": ticker, "limit": limit})

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

    async def get_ratios_ttm(self, ticker: str) -> dict | list:
        return await self.get("/ratios-ttm", {"symbol": ticker})

    async def get_enterprise_values(self, ticker: str, period: str = "quarter", limit: int = 1) -> dict | list:
        return await self.get("/enterprise-values", {"symbol": ticker, "period": period, "limit": limit})

    async def get_historical_price_eod(
        self, ticker: str, from_date: str, to_date: str, group: str = "daily_prices"
    ) -> dict | list:
        # One endpoint, three data groups: `daily_prices` (US nightly / Chart daily),
        # `daily_prices_long` (US on-demand long history) and `daily_prices_intl`
        # (any non-US listing). The caller says which; the default keeps every
        # pre-P3 call site on `daily_prices`.
        return await self.get(
            "/historical-price-eod/full", {"symbol": ticker, "from": from_date, "to": to_date}, group=group
        )

    async def get_revenue_product_segmentation(self, ticker: str) -> dict | list:
        return await self.get("/revenue-product-segmentation", {"symbol": ticker})

    async def get_revenue_geographic_segmentation(self, ticker: str) -> dict | list:
        return await self.get("/revenue-geographic-segmentation", {"symbol": ticker})

    async def get_stock_news(self, ticker: str, limit: int = 30) -> dict | list:
        return await self.get("/news/stock", {"symbols": ticker, "limit": limit})

    async def get_grades_consensus(self, ticker: str) -> dict | list:
        return await self.get("/grades-consensus", {"symbol": ticker})

    async def get_grades_historical(self, ticker: str, limit: int = 120) -> dict | list:
        # Monthly point-in-time snapshots of the 5-bucket rating distribution
        # -- limit=120 (10 years of monthly rows) rather than the default,
        # since this doubles as the Rating History chart's data source.
        return await self.get("/grades-historical", {"symbol": ticker, "limit": limit})

    async def get_price_target_consensus(self, ticker: str) -> dict | list:
        return await self.get("/price-target-consensus", {"symbol": _price_target_symbol(ticker)})

    async def get_price_target_news(self, ticker: str, page: int = 0, limit: int = 100) -> dict | list:
        # One row per individual analyst price-target action (not a
        # ready-made consensus series) -- see
        # helpers/price_target_history.py, the only reconstruction consumer.
        # FMP caps this endpoint's own page size at 100 regardless of a
        # higher requested `limit` (confirmed live); callers must paginate
        # via `page` until an empty list comes back.
        return await self.get("/price-target-news", {"symbol": _price_target_symbol(ticker), "page": page, "limit": limit})

    async def get_price_target_summary(self, ticker: str) -> dict | list:
        # Ready-made recency-bucketed averages (last month/quarter/year/
        # all-time) -- see data/analyst_ratings_data.py's price_target_by_recency.
        return await self.get("/price-target-summary", {"symbol": _price_target_symbol(ticker)})

    async def get_insider_trading_search(self, ticker: str, limit: int = 100, page: int = 0) -> dict | list:
        # One row per Form 4 transaction line, ordered by FILING date newest
        # first (not transaction date -- a late filing or Form 5 can carry an
        # old transactionDate deep inside a recent page), including
        # position-only Form 3/5 disclosures with an empty transactionType --
        # see data/insider_activity_data.py's normalization. `page` is
        # 0-indexed and contiguous for a fixed `limit` (confirmed live;
        # `limit` is honored up to 1000).
        return await self.get("/insider-trading/search", {"symbol": ticker, "limit": limit, "page": page})

    async def get_insider_trading_statistics(self, ticker: str) -> dict | list:
        # Quarterly aggregates (one row per year/quarter) -- see
        # data/insider_activity_data.py's trailing-window sums.
        return await self.get("/insider-trading/statistics", {"symbol": ticker})

    async def get_financial_growth(self, ticker: str, period: str = "annual", limit: int = 1) -> dict | list:
        return await self.get("/financial-growth", {"symbol": ticker, "period": period, "limit": limit})

    async def search_symbol(self, query: str, limit: int = 10) -> dict | list:
        """Prefix-matches the ticker SYMBOL only -- confirmed empirically
        that a company-name query (e.g. "Apple") returns []. See
        search_name below for the complementary name-matching endpoint."""
        return await self.get("/search-symbol", {"query": query, "limit": limit})

    async def search_name(self, query: str, limit: int = 10) -> dict | list:
        """Substring-matches the company NAME -- confirmed empirically that
        this does not reliably prefix-match a ticker symbol the way
        search_symbol does, so the two are queried together, never as a
        fallback pair, to cover both "typed a ticker" and "typed a company
        name" (see backend/core/main.py's search endpoint)."""
        return await self.get("/search-name", {"query": query, "limit": limit})

    async def get_sp500_constituents(self) -> dict | list:
        return await self.get("/sp500-constituent")

    async def get_dowjones_constituents(self) -> dict | list:
        return await self.get("/dowjones-constituent")

    async def get_nasdaq_constituents(self) -> dict | list:
        return await self.get("/nasdaq-constituent")

    async def get_financial_statement_full_as_reported(self, ticker: str, period: str, limit: int) -> dict | list:
        # Raw SEC-XBRL-tag dump, NOT the standardized schema the other
        # methods above use -- field names are the filer's own XBRL tags, so
        # they are not guaranteed consistent across companies (see
        # npl.py::compute_npl_ratio for how this is handled defensively).
        return await self.get(
            "/financial-statement-full-as-reported", {"symbol": ticker, "period": period, "limit": limit}
        )


fmp_client = FMPClient()
