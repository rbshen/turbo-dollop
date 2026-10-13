"""A short in-memory cache for the Chart tab when a VIEWER asks (docs/specs/auth.md, "Viewer rules").

GET /api/tickers/{t}/chart is the one ticker read with no cache-only mode: every request fetches bars and corporate events live from FMP
(data/chart_data.py). An admin keeps that. A viewer's request goes through this cache instead, keyed by (ticker, range) with a TTL of
`Settings.viewer_chart_cache_seconds` (default 60, 0 = off), and concurrent misses for the same key share one fetch, so any number of
viewers cost at most one live chart load per ticker and view per TTL. Per process and in memory: nothing is stored on disk, a restart
empties it, and a failed load is never cached (the error propagates, the next request retries). The API token bucket still applies to the
fetch itself (clients/fmp_client.py)."""

import asyncio
import time
from collections.abc import Awaitable, Callable

from core.config import settings
from core.schemas import ChartOut
from core.tickers import normalize_ticker

MAX_ENTRIES = 256
_monotonic = time.monotonic  # tests patch this


class ViewerChartCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], tuple[float, ChartOut]] = {}
        self._inflight: dict[tuple[str, str], asyncio.Task] = {}

    def clear(self) -> None:
        self._entries.clear()
        self._inflight.clear()

    def _trim(self, now: float) -> None:
        for key in [k for k, (expires, _) in self._entries.items() if expires <= now]:
            del self._entries[key]
        while len(self._entries) >= MAX_ENTRIES:
            del self._entries[min(self._entries, key=lambda k: self._entries[k][0])]

    async def get(self, ticker: str, range_key: str, load: Callable[[], Awaitable[ChartOut]]) -> ChartOut:
        ttl = settings.viewer_chart_cache_seconds
        if ttl <= 0:
            return await load()
        key = (normalize_ticker(ticker), range_key)
        now = _monotonic()
        hit = self._entries.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(load())
            self._inflight[key] = task

            def done(finished: asyncio.Task, key=key) -> None:
                self._inflight.pop(key, None)
                if not finished.cancelled() and finished.exception() is None:
                    self._trim(_monotonic())
                    self._entries[key] = (_monotonic() + settings.viewer_chart_cache_seconds, finished.result())

            task.add_done_callback(done)
        return await asyncio.shield(task)


viewer_chart_cache = ViewerChartCache()
