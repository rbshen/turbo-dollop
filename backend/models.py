from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint


class FundamentalsCache(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("ticker", "statement_type", "period", name="uq_fundamentals_cache_key"),)

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    statement_type: str
    period: str
    fetched_at: datetime
    raw_json: str
