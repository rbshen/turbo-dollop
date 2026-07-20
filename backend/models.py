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


class IndexConstituent(SQLModel, table=True):
    """A ticker's membership in a named index (e.g. "sp500"), scraped from
    Wikipedia since FMP's own constituents endpoint is unavailable on this
    plan (see sp500_scraper.py). Refreshed weekly, independent of the
    nightly per-ticker fundamentals fetch -- index membership changes a
    handful of times a year, not nightly."""

    __table_args__ = (UniqueConstraint("index_name", "ticker", name="uq_index_constituent"),)

    id: int | None = Field(default=None, primary_key=True)
    index_name: str = Field(index=True)
    ticker: str = Field(index=True)
    company_name: str
    sector: str | None = None
    sub_industry: str | None = None
    # Wikipedia's own text for this column -- not always a clean single
    # date (some rows note a re-added date or a range), stored verbatim
    # rather than force-parsed.
    date_added: str | None = None
    last_synced_at: datetime


class GrowthCatalystNote(SQLModel, table=True):
    """Manually-curated Step 2 growth catalyst text per ticker. No FMP data
    can answer "why is this company expected to grow" -- this is a free-text
    field set directly against the DB for now, since there's no admin/edit
    UI yet (same scoping as Step 1's manually-flagged one-off booleans)."""

    ticker: str = Field(primary_key=True)
    notes: str
    updated_at: datetime
