class TickerNotFoundError(Exception):
    """Raised when FMP's own /profile lookup for a ticker comes back empty
    (a genuine 200 with no rows, not a fetch failure) -- distinct from
    httpx.HTTPError, which covers a transient FMP outage and must never be
    conflated with "this ticker doesn't exist" (see get_summary)."""

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        super().__init__(f"No FMP profile data for ticker {ticker!r}")
