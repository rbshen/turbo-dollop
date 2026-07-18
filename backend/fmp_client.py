import httpx

from config import settings


class FMPClient:
    """Thin wrapper around the Financial Modeling Prep REST API.

    Endpoint-specific methods (income statement, cash flow, etc.) are added
    in a later phase once the data requirements are implemented; this is
    generic request plumbing only.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = base_url or settings.fmp_base_url
        self.api_key = api_key or settings.fmp_api_key

    async def get(self, endpoint: str, params: dict | None = None) -> dict | list:
        query = {**(params or {}), "apikey": self.api_key}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            response = await client.get(endpoint, params=query)
            response.raise_for_status()
            return response.json()


fmp_client = FMPClient()
