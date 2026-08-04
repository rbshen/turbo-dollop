import httpx

from config import settings


class AlphaVantageThrottled(Exception):
    """Raised when Alpha Vantage's own throttle response is detected --
    HTTP 200 with an "Information" (observed live, 2026-08-04) or "Note"
    (documented elsewhere, not yet observed) key in the body instead of
    real data. httpx's raise_for_status() never fires for this since the
    status code is 200, so it must be checked explicitly. Confirmed live: a
    burst of calls within ~1s of each other gets this on roughly every
    other call, well before the 25/day daily cap is even reached."""


class AlphaVantageClient:
    """Thin wrapper around Alpha Vantage's REST API, mirroring
    FMPClient's shape (own base_url/api_key from settings, one generic
    get()) -- but deliberately without FMPClient's pacing/429-retry loop.
    Alpha Vantage's throttle is a 200-with-body, not a 429, and retrying
    against a 25/day free-tier cap would waste quota rather than protect
    it -- callers (see news_sentiment_data.py) are expected to treat
    AlphaVantageThrottled as a fetch failure, not something to retry here.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = base_url or settings.alpha_vantage_base_url
        self.api_key = api_key or settings.alpha_vantage_api_key

    async def get(self, params: dict) -> dict:
        query = {**params, "apikey": self.api_key}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(self.base_url, params=query)
        response.raise_for_status()
        data = response.json()
        throttle_message = data.get("Information") or data.get("Note")
        if throttle_message:
            raise AlphaVantageThrottled(throttle_message)
        return data

    async def get_news_sentiment(self, ticker: str, limit: int = 1000) -> dict:
        # limit=1000 is the only value confirmed live to actually change the
        # response size -- 5, 200, and other values well below AV's own
        # floor all silently returned exactly 50 items regardless (verified
        # 2026-08-04), so a smaller "cost-conscious" limit doesn't actually
        # reduce anything and would just risk under-fetching real coverage.
        return await self.get({"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": limit})


alpha_vantage_client = AlphaVantageClient()
