from datetime import date, datetime

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


class TickerMoat(SQLModel, table=True):
    """User-set Economic Moat classification -- manually curated, never
    fetched from FMP (no data provider has this). Absence of a row means
    "not set", the default for every ticker; Overall Assessment ignores
    moat entirely in that case (see scoring/overall.py). Same
    non-FundamentalsCache treatment as GrowthCatalystNote, for the same
    reason (user-authored, not fetched). Editable via the ticker page's
    Economic Moat tab, gated behind a confirm step in the UI."""

    ticker: str = Field(primary_key=True)
    moat: str  # "no_moat" | "narrow_moat" | "wide_moat"
    updated_at: datetime


class MoatScoreConfig(SQLModel, table=True):
    """Configurable point values (0-100 scale, same as every step score)
    each moat state contributes to Overall Assessment once a ticker has a
    moat set -- editable via /settings, same lazy-seed get-or-create
    pattern as DiscountRateConfig (see moat.py). Singleton row, keyed on a
    fixed `key` the way DiscountRateConfig is keyed by region -- no region
    concept applies here, just one global config."""

    key: str = Field(primary_key=True, default="default")
    wide_moat_score: float
    narrow_moat_score: float
    no_moat_score: float
    updated_at: datetime


class SavedScreenerFilter(SQLModel, table=True):
    """A user-named snapshot of the Screener page's full filter/sort/universe
    state (see frontend/lib/screenerFilters.ts's ScreenerFilterState), so a
    frequently-used view can be reloaded instead of rebuilt by hand each
    time. Global list, no per-user scoping (this app has no auth concept --
    same as TickerMoat/DiscountRateConfig). filters_json stores the
    ScreenerFilterState object as-is (verbatim JSON, not decomposed into
    columns) since its shape is expected to keep growing as new filter
    fields are added -- same "store raw, don't force a rigid schema"
    reasoning as FundamentalsCache.raw_json."""

    __table_args__ = (UniqueConstraint("name", name="uq_saved_screener_filter_name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    universe: str
    sort_field: str
    sort_direction: str
    filters_json: str
    created_at: datetime
    updated_at: datetime


class Watchlist(SQLModel, table=True):
    """A user-named list of tickers, browsable from the /watchlist page.
    Global list, no per-user scoping (same as SavedScreenerFilter/TickerMoat
    -- this app has no auth concept). sort_field/sort_direction persist the
    table's last-chosen sort so it's remembered across visits, same role
    SavedScreenerFilter's own sort_field/sort_direction play for a saved
    Screener view."""

    __table_args__ = (UniqueConstraint("name", name="uq_watchlist_name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    sort_field: str = "ticker"
    sort_direction: str = "asc"
    created_at: datetime
    updated_at: datetime


class WatchlistTicker(SQLModel, table=True):
    """One ticker's membership in a Watchlist. No SQLite-level ON DELETE
    CASCADE (this app never enables PRAGMA foreign_keys) -- deleting a
    Watchlist must explicitly delete its WatchlistTicker rows first, see
    watchlists.py::delete_watchlist."""

    __table_args__ = (UniqueConstraint("watchlist_id", "ticker", name="uq_watchlist_ticker"),)

    id: int | None = Field(default=None, primary_key=True)
    watchlist_id: int = Field(foreign_key="watchlist.id", index=True)
    ticker: str
    added_at: datetime


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
    # None when no moat is set for this ticker -- Overall Assessment
    # ignores moat entirely in that case (see scoring/overall.py).
    moat: str | None = None
    moat_score: float | None = None
    overall_score: int | None = None
    overall_verdict: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    beta: float | None = None
    # "undervalued" / "fair" / "overvalued" -- lifted straight from the
    # Step 3 verdict `get_summary` already computes (ticker_summary.py's
    # `fair_value_verdict`), same source as the ticker header's
    # FairValuePill. Not a new Step 3 call: `compute_ticker_score` already
    # fetches summary for market_cap/pe_ratio/beta above.
    valuation_verdict: str | None = None
    # Step 2's analyst-estimate CAGR % (EPS basis preferred, revenue
    # fallback -- see CLAUDE.md's Step 2 deviation note), lifted straight
    # from Step2Out.growth_rate. None when Step 2 has no usable projection.
    growth_rate: float | None = None
    computed_at: datetime


class PriceTargetSnapshot(SQLModel, table=True):
    """Monthly point-in-time snapshot of FMP's price-target-consensus per
    ticker, written by monthly_price_target_snapshot.py. FMP has no
    historical price-target-consensus series of its own (unlike
    grades-historical, which is already a ready-made monthly series) -- this
    table exists purely to accumulate one going forward, feeding the Analyst
    Ratings tab's price-target history line and the Recommendation Details
    table's "N ago" Target column once enough months have been captured.

    Deliberately append-only, unlike every other table in this file: no
    UniqueConstraint, plain session.add()/commit() inserts (see
    monthly_price_target_snapshot.py), never upserted via cache.get_or_fetch
    -- the whole point is to preserve every past snapshot, not overwrite the
    latest value the way FundamentalsCache/TickerScore do."""

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    snapshot_date: date
    target_consensus: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    target_median: float | None = None
    fetched_at: datetime
