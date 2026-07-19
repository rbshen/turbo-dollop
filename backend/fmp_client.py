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

    async def get_profile(self, ticker: str) -> dict | list:
        return await self.get("/profile", {"symbol": ticker})

    async def get_quote(self, ticker: str) -> dict | list:
        return await self.get("/quote", {"symbol": ticker})

    async def get_price_change(self, ticker: str) -> dict | list:
        return await self.get("/stock-price-change", {"symbol": ticker})

    async def get_analyst_estimates(self, ticker: str) -> dict | list:
        return await self.get("/analyst-estimates", {"symbol": ticker, "period": "annual", "limit": 10})

    async def get_ratios(self, ticker: str) -> dict | list:
        return await self.get("/ratios", {"symbol": ticker, "limit": 1})

    async def get_earnings(self, ticker: str) -> dict | list:
        return await self.get("/earnings", {"symbol": ticker, "limit": 8})

    async def get_income_statement(self, ticker: str, period: str, limit: int) -> dict | list:
        return await self.get("/income-statement", {"symbol": ticker, "period": period, "limit": limit})

    async def get_cash_flow_statement(self, ticker: str, period: str, limit: int) -> dict | list:
        return await self.get("/cash-flow-statement", {"symbol": ticker, "period": period, "limit": limit})

    async def get_balance_sheet_statement(self, ticker: str, period: str, limit: int) -> dict | list:
        return await self.get("/balance-sheet-statement", {"symbol": ticker, "period": period, "limit": limit})


fmp_client = FMPClient()
