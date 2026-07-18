from datetime import date

from pydantic import BaseModel


class TickerSummaryOut(BaseModel):
    company_name: str | None = None
    ticker: str
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    market_cap: float | None = None
    beta: float | None = None
    perf_1m: float | None = None
    perf_6m: float | None = None
    eps_growth_3_5y: float | None = None
    pe_ratio: float | None = None
    next_earnings_date: date | None = None
    # Placeholder only — real fair value calculation is out of scope for this phase.
    fair_value_price: float | None = None
    fair_value_verdict: str | None = None
