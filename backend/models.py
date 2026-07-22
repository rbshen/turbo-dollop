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


class DiscountRateConfig(SQLModel, table=True):
    """Manually-maintained CAPM inputs for Step 3's discount rate (see
    step6_intrinsic_value_calculation_prompt.md §5) -- Risk-Free Rate and
    Market Risk Premium are both 5-year trailing averages sourced from
    market-risk-premia.com, deliberately not auto-fetched (that source's
    terms only support citing the number, not automated re-fetching; see
    CLAUDE.md). Editable via the /settings page. Keyed by region so a
    China/HK row can be added later without a schema change, even though
    only "US" is exposed in the UI today -- this app's screener is S&P 500
    (US-listed) only. Beta stays live per-ticker from FMP, untouched by
    this table."""

    region: str = Field(primary_key=True)
    risk_free_rate: float
    market_risk_premium: float
    updated_at: datetime


class TickerScore(SQLModel, table=True):
    """Pre-computed Step 1/2/4/5 + Overall Assessment scores for the
    Screener page (see ticker_score.py) -- a denormalized read-model kept
    separate from the live per-ticker pages, which still compute their own
    scores fresh on each view. Populated two ways: the nightly fetch job
    (after fetching each ticker's raw data) and the standalone
    recompute_ticker_scores.py script (cache-only, zero FMP calls, for
    re-scoring all tickers immediately after a scoring-logic change)."""

    ticker: str = Field(primary_key=True)
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    company_type: str | None = None
    step1_score: int | None = None
    step1_verdict: str | None = None
    step2_score: int | None = None
    step2_verdict: str | None = None
    step4_score: int | None = None
    step4_verdict: str | None = None
    step5_score: int | None = None
    step5_verdict: str | None = None
    overall_score: int | None = None
    overall_verdict: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    beta: float | None = None
    computed_at: datetime
