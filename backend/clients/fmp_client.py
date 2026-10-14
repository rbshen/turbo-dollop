import asyncio
import logging
import time

import httpx

from core.config import settings
from core.data_groups import (
    CANARY_SYMBOL_OVERRIDES,
    PROBE_ENDPOINTS,
    VARIANT_GROUPS,
    clear_restricted,
    clear_variant,
    describe_off,
    effective_state,
    get_snapshot,
    group_for_endpoint,
    mark_restricted,
    mark_variant_restricted,
    record_group_failure,
    record_group_success,
    record_variant_probe,
    restricted_variants,
    set_key_problem,
    variant_of,
    variant_restriction,
    variant_unavailable,
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


class FMPCircuitOpenError(httpx.HTTPError):
    """Raised by FMPClient (no network call) while the auth circuit breaker is open: FMP answered 401/403
    `fmp_auth_breaker_threshold` times in a row, so requests pause for `fmp_auth_breaker_cooldown_seconds`. A plain
    httpx.HTTPError (like the 401 itself was), so safe_fetch and every `except httpx.HTTPError` site already handle it
    as a failed fetch. It is not an FMPDisabledError: no data group is off, the key is the problem."""


class FMPInvalidResponseError(httpx.HTTPError):
    """FMP answered HTTP 200 with something that is not data: a body that is not JSON, JSON that is neither an object
    nor a list, or an object carrying an error key ("Error Message"). A plain httpx.HTTPError, so safe_fetch and every
    `except httpx.HTTPError` site treat it as the failed fetch it is, and get_or_fetch never caches it. The message
    names the endpoint only, never the body."""


# A 200 object with one of these keys (any case) is an error answer, not data.
_ERROR_BODY_KEYS = frozenset({"error message", "error"})


def _checked_body(response: httpx.Response, endpoint: str) -> dict | list:
    """The decoded JSON body of a successful FMP answer, or FMPInvalidResponseError (see above)."""
    try:
        body = response.json()
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        raise FMPInvalidResponseError(f"FMP returned a non-JSON body for {endpoint}") from None
    if isinstance(body, dict):
        if any(isinstance(k, str) and k.lower() in _ERROR_BODY_KEYS for k in body):
            raise FMPInvalidResponseError(f"FMP returned an error object for {endpoint}")
        return body
    if isinstance(body, list):
        return body
    raise FMPInvalidResponseError(f"FMP returned an unexpected {type(body).__name__} body for {endpoint}")


class FMPLocalRateLimitError(httpx.HTTPError):
    """Raised by FMPClient (no network call) when the API process's own token bucket cannot serve a request within
    `fmp_api_max_wait_seconds`. Handled like any failed fetch (httpx.HTTPError)."""


class _TokenBucket:
    """Token bucket for the API process: `rate_per_minute` tokens refill per minute up to `burst`. acquire() reserves a
    token and sleeps until it is due; when the wait would exceed `max_wait` it raises FMPLocalRateLimitError without
    reserving, so a flood cannot build an unbounded queue."""

    def __init__(self, rate_per_minute: float, burst: int, max_wait: float) -> None:
        self.rate = rate_per_minute / 60.0
        self.capacity = float(max(burst, 1))
        self.max_wait = max_wait
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            wait = 0.0 if self._tokens >= 1.0 else (1.0 - self._tokens) / self.rate
            if wait > self.max_wait:
                raise FMPLocalRateLimitError(f"FMP request rate limit reached; retry in {wait:.0f}s")
            self._tokens -= 1.0  # may go negative: later callers queue behind this reservation
        if wait > 0:
            await asyncio.sleep(wait)


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


class FMPVariantUnavailableError(FMPDisabledError):
    """Raised by FMPClient.get, with NO network call, for a request VARIANT (endpoint + period/limit) FMP already
    refused with a canary-confirmed 402 -- "not available on this plan". The group itself is live and every other
    variant works. Subclasses FMPDisabledError (so httpx.HTTPError), so safe_fetch and every `except
    httpx.HTTPError` site treats it as "no data for this variant", exactly like an empty response; core.cache
    catches it to serve a stale cached row and never writes anything for it."""

    def __init__(self, message: str, group: str, variant_key: str, label: str) -> None:
        super().__init__(message)
        self.group = group
        self.variant_key = variant_key
        self.label = label


_CANARY_SYMBOL = "AAPL"


def _canary_params(params: dict, endpoint: str | None = None) -> dict | None:
    """The same request with the symbol swapped for AAPL (or the endpoint's own
    CANARY_SYMBOL_OVERRIDES symbol -- SPY for /etf/info), or None when there is
    nothing to swap (symbol-less endpoint, or already the canary -- the failing
    call itself then IS the canary)."""
    canary_symbol = CANARY_SYMBOL_OVERRIDES.get(endpoint, _CANARY_SYMBOL) if endpoint else _CANARY_SYMBOL
    for key in ("symbol", "symbols", "query"):
        if key in params:
            if str(params[key]).upper() == canary_symbol:
                return None
            return {**params, key: canary_symbol}
    return None


def _symbol_of(params: dict | None) -> str | None:
    value = (params or {}).get("symbol")
    return str(value) if value else None


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

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        min_request_interval: float = 0.0,
        auth_breaker_threshold: int | None = None,
        auth_breaker_cooldown_seconds: float | None = None,
    ) -> None:
        self.base_url = base_url or settings.fmp_base_url
        self.api_key = api_key or settings.fmp_api_key
        self.min_request_interval = min_request_interval
        self.request_count = 0
        self._last_request_at: float | None = None
        self._pace_lock = asyncio.Lock()
        # Interactive rate limit: None until the API process turns it on (enable_api_rate_limit); cron never does.
        self._bucket: _TokenBucket | None = None
        # Auth circuit breaker (see _note_status): consecutive 401/403 answers, and when the pause ends.
        self.auth_breaker_threshold = settings.fmp_auth_breaker_threshold if auth_breaker_threshold is None else auth_breaker_threshold
        self.auth_breaker_cooldown_seconds = (
            settings.fmp_auth_breaker_cooldown_seconds if auth_breaker_cooldown_seconds is None else auth_breaker_cooldown_seconds
        )
        self._auth_failures = 0
        self._breaker_open_until: float | None = None

    def enable_api_rate_limit(
        self, rate_per_minute: float | None = None, burst: int | None = None, max_wait: float | None = None
    ) -> None:
        """Turns the token bucket on for this process (core/main.py's lifespan calls it; the cron entry points never do,
        so their pacing is untouched). A rate of 0 or less leaves it off."""
        rate = settings.fmp_api_rate_per_minute if rate_per_minute is None else rate_per_minute
        if rate <= 0:
            self._bucket = None
            return
        self._bucket = _TokenBucket(
            rate,
            settings.fmp_api_burst if burst is None else burst,
            settings.fmp_api_max_wait_seconds if max_wait is None else max_wait,
        )

    def disable_api_rate_limit(self) -> None:
        self._bucket = None

    @property
    def auth_breaker_open(self) -> bool:
        return self._breaker_open_until is not None and time.monotonic() < self._breaker_open_until

    def reset_auth_breaker(self) -> None:
        self._auth_failures = 0
        self._breaker_open_until = None

    def _check_auth_breaker(self) -> None:
        if self.auth_breaker_open:
            remaining = max(0.0, (self._breaker_open_until or 0.0) - time.monotonic())
            raise FMPCircuitOpenError(
                f"FMP requests are paused for another {remaining:.0f}s after {self._auth_failures} consecutive 401/403 "
                f"responses; check FMP_API_KEY"
            )

    def _note_status(self, status: int, endpoint: str) -> None:
        """Circuit breaker bookkeeping for one real answer. 401/403 count; a success or a 402 (the key was accepted, the plan
        was not) resets the run; anything else (429, 5xx, 404) neither counts nor resets. Once the run reaches the
        threshold the breaker opens for the cooldown; when the cooldown ends the next request goes through as a trial,
        and one more 401/403 re-opens it at once because the run is still at the threshold."""
        if status in (401, 403):
            self._auth_failures += 1
            threshold = self.auth_breaker_threshold
            if threshold > 0 and self._auth_failures >= threshold:
                self._breaker_open_until = time.monotonic() + self.auth_breaker_cooldown_seconds
                detail = (
                    f"HTTP {status} from {endpoint}, {self._auth_failures} in a row: FMP requests paused "
                    f"{self.auth_breaker_cooldown_seconds:.0f}s (check FMP_API_KEY)"
                )
                logger.error("FMP auth circuit breaker open: %s", detail)
                _safe(set_key_problem, detail)  # the existing key-problem banner (Settings > FMP data groups)
        elif status < 400 or status == 402:
            if self._auth_failures or self._breaker_open_until is not None:
                self.reset_auth_breaker()

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
        if group in VARIANT_GROUPS:
            restricted = variant_restriction(group, endpoint, params)
            if restricted is not None:
                self._record_unavailable(params, restricted.variant_key)
                raise FMPVariantUnavailableError(
                    f"{restricted.label} is not available on this plan (FMP 402 since "
                    f"{restricted.restricted_since:%Y-%m-%d}) -- no call made to {endpoint}",
                    group=group, variant_key=restricted.variant_key, label=restricted.label,
                )
        query = {**(params or {}), "apikey": self.api_key}
        self._check_auth_breaker()  # before the try below: a paused call is not a group failure
        try:
            response = await self._send(endpoint, query)
        except (FMPCircuitOpenError, FMPLocalRateLimitError):
            raise  # our own protection, not a failing group
        except httpx.HTTPError as exc:  # transport-level (timeout/connect): a failing group, never a restriction
            record_group_failure(group, type(exc).__name__)
            raise
        status = response.status_code
        if status < 400:
            try:
                body = _checked_body(response, endpoint)
            except FMPInvalidResponseError as exc:
                record_group_failure(group, "invalid response")
                logger.warning("%s", exc)
                raise
            record_success("fmp")
            record_group_success(group)
            _clear_key_problem_if_set()
            return body
        if status in (401, 403):
            # A key problem, not a plan restriction: global warning, no group blamed. (When this answer opened the
            # circuit breaker, _note_status already wrote the richer "paused" detail; keep it.)
            if not self.auth_breaker_open:
                _safe(set_key_problem, f"HTTP {status} from {endpoint}")
        elif status == 402:
            if group in VARIANT_GROUPS:
                await self._handle_variant_restriction(group, endpoint, params or {})
            else:
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
            self._check_auth_breaker()
            if self._bucket is not None:
                await self._bucket.acquire()
            await self._pace()
            self.request_count += 1
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                response = await client.get(endpoint, params=query)
            self._note_status(response.status_code, endpoint)
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

    @staticmethod
    def _record_unavailable(params: dict | None, variant_key: str) -> None:
        symbol = _symbol_of(params)
        if symbol:
            variant_unavailable.record(symbol, variant_key)

    async def _handle_variant_restriction(self, group: str, endpoint: str, params: dict) -> None:
        """The variant-level counterpart of _handle_plan_restriction (groups in VARIANT_GROUPS). A 402 can be
        symbol-scoped (0941.HK, BRK.B and BF.B 402 on every statement endpoint), so the failing call alone never
        restricts anything: replay the SAME variant (endpoint + period/limit, nothing else) for the canary symbol,
        and record the restriction against that variant only if the canary ALSO gets a 402. A canary that answers
        200 means symbol-scoped (nothing recorded); a 429, a 5xx or a transport error means inconclusive (nothing
        recorded). The group is never marked."""
        key, vparams = variant_of(endpoint, params)
        canary_symbol = CANARY_SYMBOL_OVERRIDES.get(endpoint, _CANARY_SYMBOL)
        failing_symbol = _symbol_of(params)
        if failing_symbol is None or failing_symbol.upper() == canary_symbol:
            confirmed = True  # the failing call is its own canary
        else:
            try:
                response = await self._send(endpoint, {**vparams, "symbol": canary_symbol, "apikey": self.api_key})
                confirmed = response.status_code == 402
            except httpx.HTTPError:
                confirmed = False  # inconclusive -- never restrict on a failed probe
        if confirmed:
            _safe(mark_variant_restricted, group, endpoint, params, f"HTTP 402 on {key} (canary confirmed)", canary_symbol)
            self._record_unavailable(params, key)
        else:
            logger.warning("FMP 402 for %s was symbol-scoped or unconfirmed (canary not 402); variant %s left available", endpoint, key)

    async def _handle_plan_restriction(self, group: str, endpoint: str, params: dict) -> None:
        """A 402 can be symbol-scoped (e.g. a non-US symbol on a US-only
        plan), so the failing call alone never disables a group: probe a
        canary (AAPL, same endpoint) and mark the group plan_restricted only
        if the canary ALSO gets a 402. An endpoint with no symbol/query
        parameter has no canary to vary -- the failing call is its own
        canary."""
        canary = _canary_params(params, endpoint)
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
            try:
                _checked_body(response, endpoint)
            except FMPInvalidResponseError:
                return "inconclusive"  # a 200 that is not data proves nothing
            _safe(clear_restricted, group)
            return "ok"
        if response.status_code == 402:
            _safe(mark_restricted, group, f"HTTP 402 on {endpoint} (re-probe)")
            return "restricted"
        if response.status_code in (401, 403):
            _safe(set_key_problem, f"HTTP {response.status_code} from {endpoint} (re-probe)")
        return "inconclusive"

    async def probe_variant(self, group: str, variant_key: str) -> str:
        """Re-test one restricted variant with ITS OWN replay (the variant's parameters + the canary symbol), bypassing
        the variant gate. "ok" (200: the restriction is cleared), "restricted" (402: stays, stamped) or "inconclusive"
        (anything else: untouched). Only this exact request can clear it."""
        state = next((v for v in restricted_variants(group) if v.variant_key == variant_key), None)
        if state is None:
            return "inconclusive"
        try:
            response = await self._send(state.endpoint, {**state.params, "apikey": self.api_key})
        except httpx.HTTPError:
            return "inconclusive"
        if response.status_code < 400:
            try:
                _checked_body(response, state.endpoint)
            except FMPInvalidResponseError:
                return "inconclusive"  # a 200 that is not data proves nothing
            _safe(clear_variant, group, variant_key, "re-probe succeeded")
            return "ok"
        if response.status_code == 402:
            _safe(record_variant_probe, group, variant_key, f"HTTP 402 on {variant_key} (re-probe)")
            return "restricted"
        if response.status_code in (401, 403):
            _safe(set_key_problem, f"HTTP {response.status_code} from {state.endpoint} (re-probe)")
        return "inconclusive"

    async def reprobe_restricted_variants(self, group: str | None = None) -> dict[str, str]:
        """Re-probe every restricted variant (weekly, when the plan is edited, and from Settings), each with its
        own replay. No-op while the master switch is off or the variant's group is not live (zero calls)."""
        if not get_snapshot().master_on:
            return {}
        out: dict[str, str] = {}
        for state in restricted_variants(group):
            if effective_state(state.group)[0]:
                out[f"{state.group}:{state.variant_key}"] = await self.probe_variant(state.group, state.variant_key)
        return out

    async def reprobe_restricted(self) -> dict[str, str]:
        """Groups AND variants: what the weekly health check and a plan edit call."""
        return {**await self.reprobe_restricted_groups(), **await self.reprobe_restricted_variants()}

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

    async def get_etf_info(self, ticker: str) -> dict | list:
        """Fund facts + embedded sector weights (one row; `[]` for a non-ETF). The only ETF
        endpoint the app uses -- never /etf/holdings, /etf/sector-weightings, /etf/country-weightings
        or /etf/asset-exposure."""
        return await self.get("/etf/info", {"symbol": ticker})

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

    async def get_splits(self, ticker: str) -> dict | list:
        # One row per split, newest first (`numerator`/`denominator`, e.g. 4/1).
        return await self.get("/splits", {"symbol": ticker})

    async def get_delisted_companies(self, page: int, limit: int = 100) -> dict | list:
        # The whole market's delisted list, newest first. FMP clamps `limit` to 100, so the
        # full list (~15.6k rows) is ~157 pages; a symbol can appear more than once (reuse).
        return await self.get("/delisted-companies", {"page": page, "limit": limit})

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
        # One endpoint, two data groups: `daily_prices` (nightly / Chart daily) and
        # `daily_prices_long` (on-demand long history). The caller says which; the
        # default keeps every pre-P3 call site on `daily_prices`.
        return await self.get(
            "/historical-price-eod/full", {"symbol": ticker, "from": from_date, "to": to_date}, group=group
        )

    async def get_historical_chart_1hour(self, ticker: str, from_date: str, to_date: str) -> dict | list:
        # Regular-trading-hours hourly bars, newest first, timestamps naive ET, labelled by bar
        # start (09:30..15:30). NEVER `extended=true` (clock-anchored, wrong labelling). The
        # literal path is what tests/test_data_groups_registry.py scans for.
        return await self.get("/historical-chart/1hour", {"symbol": ticker, "from": from_date, "to": to_date})

    # Sector / industry average P/E (data group sector_industry_pe). Every call passes `exchange`: omitting it silently
    # defaults to NASDAQ. Snapshots need a `date`; the historical calls need explicit from/to (the default window
    # ends 2024-03-01). Rows: {"date", "sector"|"industry", "exchange", "pe"}; a series with no data is `[]`.
    async def get_sector_pe_snapshot(self, on_date: str, exchange: str) -> dict | list:
        return await self.get("/sector-pe-snapshot", {"date": on_date, "exchange": exchange})

    async def get_industry_pe_snapshot(self, on_date: str, exchange: str) -> dict | list:
        return await self.get("/industry-pe-snapshot", {"date": on_date, "exchange": exchange})

    async def get_historical_sector_pe(self, sector: str, exchange: str, from_date: str, to_date: str) -> dict | list:
        return await self.get(
            "/historical-sector-pe", {"sector": sector, "exchange": exchange, "from": from_date, "to": to_date}
        )

    async def get_historical_industry_pe(self, industry: str, exchange: str, from_date: str, to_date: str) -> dict | list:
        return await self.get(
            "/historical-industry-pe", {"industry": industry, "exchange": exchange, "from": from_date, "to": to_date}
        )

    async def get_revenue_product_segmentation(self, ticker: str) -> dict | list:
        return await self.get("/revenue-product-segmentation", {"symbol": ticker})

    async def get_revenue_geographic_segmentation(self, ticker: str) -> dict | list:
        return await self.get("/revenue-geographic-segmentation", {"symbol": ticker})

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
