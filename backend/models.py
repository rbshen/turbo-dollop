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


class GrowthCatalystNote(SQLModel, table=True):
    """Manually-curated Step 2 growth catalyst text per ticker. No FMP data
    can answer "why is this company expected to grow" -- this is a free-text
    field set directly against the DB for now, since there's no admin/edit
    UI yet (same scoping as Step 1's manually-flagged one-off booleans)."""

    ticker: str = Field(primary_key=True)
    notes: str
    updated_at: datetime
