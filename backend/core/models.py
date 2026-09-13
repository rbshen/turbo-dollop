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


class NewsCache(SQLModel, table=True):
    """Short-TTL cache for FMP's /news/stock response per ticker (see
    news_data.py) -- deliberately its own table, not a FundamentalsCache
    row, since news is refreshed on the order of minutes
    (`Settings.news_cache_ttl_minutes`) rather than days, and has no
    statement_type/period dimension to key on."""

    ticker: str = Field(primary_key=True)
    fetched_at: datetime
    raw_json: str


class YahooPriceCache(SQLModel, table=True):
    """Daily OHLCV bars sourced from Yahoo Finance (see clients/yahoo_client.py,
    clients/yahoo_cache.py) -- deliberately its own table, not a
    FundamentalsCache row, for the same reason NewsCache is its own table
    above: this is a different provider entirely (decoupled from the
    FMP_ENABLED kill switch on purpose, so trend analysis keeps working
    through an FMP pause) and a different shape (one row per ticker per
    trading day, typed OHLCV columns, not a single raw_json blob per
    statement-type/period). Refreshed on Settings.yahoo_price_cache_staleness_days
    (default 1 day -- much tighter than FundamentalsCache's 7, since this is
    trading-day-grain data that gets a new bar every day the nightly trend
    job runs, unlike fundamentals which only change quarterly)."""

    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_yahoo_price_cache_key"),)

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    fetched_at: datetime


class TrendAnalysis(SQLModel, table=True):
    """Latest trend-structure analysis per ticker (swing/BOS/blended-score
    engine, see analysis/trend_structure/ and data/trend_analysis_data.py)
    -- sourced from Yahoo Finance (YahooPriceCache above), independent of
    FMP entirely. Ticker-PK, no surrogate id, `computed_at` (not
    `fetched_at`) naming -- same "this is a derived value" convention as
    TickerScore, not a raw fetch cache. Upserted per run, latest-only (no
    history needed), written by pipeline/nightly_trend_calculation.py.

    last_confirmed_swing_json/warning_swing_json are plain `str`, manually
    json.dumps/loads'd -- there is no native JSON column type anywhere in
    this codebase (see FundamentalsCache.raw_json/SavedScreenerFilter.
    filters_json/TickerCustomValuation.parameters_json for the established
    convention this follows). Either can be None: last_confirmed_swing_json
    is None only for a brand-new/too-thin swing history that's never
    produced a weak-confirmed-or-stronger swing yet; warning_swing_json is
    None whenever warning_flag is False."""

    ticker: str = Field(primary_key=True)
    computed_at: datetime
    trend_state: str  # "uptrend" | "downtrend"
    magnitude_tier: str | None = None  # "weak" | "confirmed" | "strong" | None
    persistence_count: int
    bars_since_confirmation: int | None = None
    last_confirmed_swing_json: str | None = None
    warning_flag: bool
    warning_swing_json: str | None = None
    # Whether ANY pullback warning has fired since trend_state's own most
    # recent flip -- lets the Trend Continuation card distinguish "no
    # pullback since the last flip" from "a pullback occurred and has since
    # been resolved" (see analysis/trend_structure/types.py::
    # TrendStructureResult.pullback_occurred_since_flip). Nullable for the
    # usual _add_missing_columns-has-no-backfill reason: a pre-existing row
    # reads NULL until the next nightly run rewrites it.
    pullback_occurred_since_flip: bool | None = None
    # The swing that triggered trend_state's own most recent genuine flip
    # (see analysis/trend_structure/state_machine.py::TrendMachineState.
    # flip_swing). trend_started_is_lower_bound=True means no genuine flip
    # has occurred anywhere in the ticker's available cached history -- the
    # current trend covers the entire history, so this date is the
    # earliest we can see, not necessarily the true start (mirrors
    # weinstein_stage_since_date/_is_lower_bound's identical convention).
    # Nullable for the same _add_missing_columns-has-no-backfill reason as
    # pullback_occurred_since_flip above.
    trend_started_json: str | None = None
    trend_started_is_lower_bound: bool | None = None
    # Every pullback cycle that has resolved within the CURRENT trend --
    # see analysis/trend_structure/state_machine.py::TrendMachineState.
    # pullback_history and TrendAnalysisOut.pullback_history's own comments
    # for the full contract. Plain `str` JSON (a list of {warning_swing,
    # resolving_swing} objects, each shaped like last_confirmed_swing_json's
    # own SwingDetail dict), same convention as every other JSON-shaped
    # field on this table (see the class docstring). Nullable for the usual
    # _add_missing_columns-has-no-backfill reason; reads as an empty list
    # (not None) at the API boundary either way, since a pre-existing row
    # and a genuinely-empty history are indistinguishable and both mean
    # "nothing to show" to a caller.
    pullback_history_json: str | None = None
    # Every confirmed LL swing within the CURRENT downtrend -- see
    # analysis/trend_structure/state_machine.py::TrendMachineState.
    # reversal_history and TrendAnalysisOut.reversal_history's own comments
    # for the full contract. Plain `str` JSON (a list of {swing,
    # ad_bullish_divergence, ad_divergence_swing_date} objects, `swing`
    # shaped like last_confirmed_swing_json's own SwingDetail dict), same
    # convention as pullback_history_json above. Nullable for the same
    # _add_missing_columns-has-no-backfill reason; reads as an empty list
    # (not None) at the API boundary either way.
    reversal_history_json: str | None = None
    efficiency_ratio: float | None = None
    regime: str | None = None  # "trending" | "range-bound" | None
    blended_score: float
    bar_level: int  # 1-5, see analysis/trend_structure/conviction.py
    # A/D Bullish Divergence (see analysis/trend_structure/classification.py)
    # -- nullable, unlike the pure engine's own always-real bool/None-date
    # output, specifically because core/db.py::_add_missing_columns adds
    # columns via a raw ALTER TABLE with no backfill: existing rows read as
    # NULL until the next nightly run rewrites every field. A nullable
    # Python type avoids a validation error on that transient legacy read;
    # every consumer already treats None the same as False.
    ad_bullish_divergence: bool | None = None
    ad_divergence_swing_date: date | None = None
    # SMA (20/50/200) position tracking (see
    # analysis/trend_structure/sma_position.py) -- nullable for the same
    # reason as ad_bullish_divergence above: _add_missing_columns's ALTER
    # TABLE has no backfill, so existing rows read NULL until the next
    # nightly run rewrites every field. cross is a plain str ("up"/"down"),
    # same enum-like-string convention trend_state/regime already use.
    sma20_position_pct: float | None = None
    sma20_cross: str | None = None
    sma50_position_pct: float | None = None
    sma50_cross: str | None = None
    sma200_position_pct: float | None = None
    sma200_cross: str | None = None
    # Weinstein Stage Analysis (see analysis/trend_structure/weinstein.py) --
    # a fully independent second lens, computed on WEEKLY bars resampled
    # from the same daily OHLCV history, not merged with the swing/BOS
    # fields above. Nullable for the same _add_missing_columns-has-no-
    # backfill reason as ad_bullish_divergence/sma20_cross: existing rows
    # read NULL until the next nightly run rewrites every field.
    # weinstein_stage: "base" | "advance" | "top" | "decline" | None, same
    # plain-str enum convention as trend_state/regime.
    weinstein_stage: str | None = None
    # First week of the CURRENT stage (see WeinsteinStageResult's own
    # docstring for the walk-back definition).
    weinstein_stage_since_date: date | None = None
    # True when the stage never differed anywhere in the available
    # (post-bootstrap) weekly history -- the true start predates the fetch
    # window, so weinstein_stage_since_date is a lower bound, not a
    # precise transition date.
    weinstein_stage_since_is_lower_bound: bool | None = None
    # How many resampled weekly bars a compute actually found -- the pure
    # engine (WeinsteinStageResult) always populates this with a real int,
    # but it's nullable HERE for the usual _add_missing_columns reason,
    # which is exactly what makes it useful: a NULL here (alongside a NULL
    # weinstein_stage) means this row has never been touched by a
    # Weinstein-aware compute at all (a legacy/never-reprocessed row),
    # while a real sub-40 int means a compute genuinely ran and found too
    # little history. Added 2026-09-06 after a real incident where CTAS/
    # ABNB (both with years of real cached history) showed the same
    # "insufficient history" UI state as a genuinely-thin ticker, purely
    # because their rows predated this feature's own deploy -- this field
    # is what lets the UI tell those two cases apart.
    weinstein_weeks_available: int | None = None
    # "Today's freshly computed stage differs from what was stored here
    # BEFORE this write" -- an ACROSS-NIGHTLY-RUNS comparison, computed in
    # data/trend_analysis_data.py's orchestration layer (needs to read the
    # previous row), deliberately NOT the same concept as
    # weinstein_breakout_confirmed below (a pure, single-run, week-over-
    # week comparison from the engine itself). False (not None) whenever
    # there's no previous stored stage to compare against yet.
    weinstein_stage_changed: bool | None = None
    weinstein_ma_slope_pct: float | None = None
    weinstein_vs_ma_pct: float | None = None
    weinstein_volume_ratio: float | None = None
    weinstein_mansfield_rs: float | None = None
    weinstein_breakout_confirmed: bool | None = None


class TechnicalEntrySignal(SQLModel, table=True):
    """Latest technical entry-signal read per (ticker, signal_type,
    timeframe) -- the first of these is BB+RSI on a 2h timeframe (see
    analysis/entry_signal/ and data/entry_signal_data.py), ported from a
    reference trading bot's signal condition (execution/backtest/
    notification logic discarded -- see CLAUDE.md). Composite PK, not a
    ticker-only PK like TrendAnalysis above, because this is explicitly
    designed to grow: future signal types (and daily-timeframe variants)
    will coexist per ticker rather than replace this one row.

    Unlike TrendAnalysis, this table is scoped to the union of every
    watchlist named W1 through W5 the nightly job reads, not the full
    tracked universe -- a ticker on none of them simply has no row
    here, which is the intended "this filter only ever matches W1-W5
    tickers" behavior, not a gap to work around.

    Originally had a `fired: bool` column, replaced by `fired_at` below
    (2026-09-09, see fired_at's own comment). Unlike core/db.py::
    _add_missing_columns' additive-only sweep, this one genuinely had to
    be DROPPED, not just left unreferenced: `fired` was NOT NULL with no
    default, so once the model stopped supplying it, every future INSERT
    would violate that constraint. See core/db.py::_drop_obsolete_columns
    (a small, explicit registry, not a general migration framework --
    matching _add_missing_columns' own minimalism)."""

    ticker: str = Field(primary_key=True)
    signal_type: str = Field(primary_key=True)  # "bb_rsi"
    timeframe: str = Field(primary_key=True)  # "2h"
    # The timestamp of the 2h bar where check_buy_signal LAST evaluated
    # true -- None if it never has. Unlike the removed `fired` boolean
    # this used to be, updating this (and pct_b/rsi/close/stop_price
    # below, which describe THIS bar, not "whatever the latest candle
    # read this run") is conditional: the nightly job only advances these
    # five fields together when a bar fires with a timestamp newer than
    # what's already stored here (see data/entry_signal_data.py::_upsert)
    # -- a quiet night leaves them untouched rather than erasing a still-
    # relevant prior fire. "Active" (whether that fire is still within the
    # 7-day confirmation window) is derived from this at read time
    # (data/entry_signal_data.py::is_entry_signal_active), never stored.
    fired_at: datetime | None = None
    pct_b: float | None = None
    rsi: float | None = None
    close: float | None = None
    # close - ATR(14) x ATR_MULTIPLIER on the fired_at bar (ported from
    # the reference bot's initial-stop calc, not its trailing/re-raise
    # logic -- there's no open position here to trail a stop for). None
    # whenever fired_at is None, and also whenever ATR itself is NaN on
    # that bar (e.g. too little history for a 14-period ATR).
    stop_price: float | None = None
    source: str  # "yahoo" (or "fmp", once that adapter is ever wired in)
    # Timestamp of the last candle actually evaluated this run (fired or
    # not) -- unlike fired_at above, this updates every nightly run
    # regardless of outcome, so every Watchlist ticker still gets a
    # heartbeat even on a quiet night.
    as_of: datetime
    computed_at: datetime  # when the nightly job produced this row

    # The three columns below exist ONLY for signal_type="warren" rows
    # (always NULL for "bb_rsi" -- added additively via core/db.py::
    # _add_missing_columns, no migration script needed since this table's
    # PK already discriminates by signal_type). See
    # analysis/warren_signal/ and data/warren_signal_data.py. For a
    # "warren" row, fired_at/rsi/close above describe the LATEST EVENT OF
    # EITHER DIRECTION (buy or sell) -- not buy-only, unlike "bb_rsi"'s own
    # fired_at -- and stop_price above is the LIVE yellowStopPrice as of
    # the last replayed bar (analysis/warren_signal/types.py::
    # WarrenReplayResult.live_stop_price), which can reflect an
    # earlier-held yellow entry, not necessarily the same bar signal_kind
    # fired on. pct_b is always NULL for "warren" (not applicable).
    signal_kind: str | None = None  # one of analysis.warren_signal.types.SIGNAL_KINDS
    gray_suppressed: bool | None = None  # yellowIsGray as of the last replayed bar
    stop_count: int | None = None  # stopCount (since the last Blue trigger) as of the last replayed bar


class TechnicalEntrySignalEvent(SQLModel, table=True):
    """Append-only history of every individual firing 2h bar, feeding the
    Chart tab's multi-marker history (see data/chart_data.py). Unlike
    TechnicalEntrySignal above -- which holds only the single latest fire
    per (ticker, signal_type, timeframe), overwritten every nightly run --
    this table accumulates one row per distinct fire and is never
    overwritten, only pruned by age (see prune_entry_signal_events in
    data/entry_signal_data.py). Purely additive: TechnicalEntrySignal
    stays exactly as before, still the only thing the API's
    single-latest-fire read and the Screener's "active" filter consult.

    Populated two ways: nightly, one row per ticker per run when
    compute_and_store_entry_signal's result.fired is True (using the same
    result already computed for the TechnicalEntrySignal upsert -- no
    change to check_buy_signal/compute_entry_signal's detection logic);
    and via a one-time backfill (pipeline/backfills/
    backfill_entry_signal_events.py) that scans up to Yahoo's own 730-day
    2h-interval history limit using compute_historical_entry_signals
    (analysis/entry_signal/engine.py).

    Surrogate `id` PK (not composite, unlike TechnicalEntrySignal) since
    this is a real accumulating time series, not a single latest-state
    row per key -- matches FundamentalsCache/YahooPriceCache's own
    surrogate-PK-plus-UniqueConstraint shape. The UniqueConstraint is
    what actually enforces one row per (ticker, signal_type, timeframe,
    fired_at), making a cron rerun's insert an idempotent no-op via
    on_conflict_do_nothing rather than a duplicate row."""

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    signal_type: str  # "bb_rsi" -- matches TechnicalEntrySignal's naming
    timeframe: str  # "2h" -- matches TechnicalEntrySignal's naming
    fired_at: datetime  # naive, Eastern-local -- same convention as TechnicalEntrySignal.fired_at
    stop_price: float | None = None
    created_at: datetime  # when this row was inserted -- auditing only, not read by any query

    __table_args__ = (UniqueConstraint("ticker", "signal_type", "timeframe", "fired_at", name="uq_entry_signal_event_key"),)


class WarrenSignalEvent(SQLModel, table=True):
    """Append-only history of every individual Warren RSI/ADX/WVF arrow
    (see analysis/warren_signal/ and data/warren_signal_data.py) -- the
    Warren-specific counterpart to TechnicalEntrySignalEvent above, kept as
    its OWN table rather than reusing that one. Reason: two different
    Warren arrows (e.g. Blue Up and Yellow Up) can fire on the exact same
    bar (verified algebraically from the reference script's own formulas),
    which would collide under TechnicalEntrySignalEvent's existing
    UniqueConstraint on (ticker, signal_type, timeframe, fired_at) -- it
    has no signal_kind column to disambiguate. core/db.py's migration
    tooling (_add_missing_columns) is additive-column-only; it cannot
    alter an existing UniqueConstraint, so widening that table's own
    constraint would need a real migration this app has no tooling for. A
    brand-new table sidesteps this entirely -- the correct constraint is
    just part of its definition from creation.

    No signal_type column (unlike TechnicalEntrySignalEvent) since this
    table is Warren-only by construction -- the table itself is the
    discriminator. `timeframe` is kept anyway, always "2h" today, for the
    same future-proofing reason TechnicalEntrySignalEvent keeps it despite
    an identical single current value.

    Unlike BB+RSI's own nightly job (which only evaluates the latest day,
    needing a separate one-time backfill script for older history -- see
    pipeline/backfills/backfill_entry_signal_events.py), Warren's nightly
    job always replays the FULL available history from scratch every run
    (see analysis/warren_signal/state_machine.py's own docstring on why
    this is safe/idempotent) -- so this table is fully populated by the
    nightly job alone, with no separate backfill script needed."""

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    timeframe: str  # "2h"
    signal_kind: str  # one of analysis.warren_signal.types.SIGNAL_KINDS
    fired_at: datetime  # naive, Eastern-local -- same convention as TechnicalEntrySignalEvent.fired_at
    # The LIVE yellowStopPrice as of this specific bar (see
    # TechnicalEntrySignal.stop_price's own comment on this same nuance) --
    # None if no yellow/gray entry had ever been held yet at this bar.
    stop_price: float | None = None
    created_at: datetime  # when this row was inserted -- auditing only, not read by any query

    __table_args__ = (UniqueConstraint("ticker", "timeframe", "fired_at", "signal_kind", name="uq_warren_signal_event_key"),)


class LiquidityZoneAnalysis(SQLModel, table=True):
    """Latest Liquidity Zone (LP) detection read per (ticker, timeframe) --
    unbreached swing-low support / swing-high resistance levels, clustered
    into zones (see analysis/liquidity_zones/ and
    data/liquidity_zone_data.py). Composite PK, not a ticker-only PK like
    TrendAnalysis above, for the same reason TechnicalEntrySignal's own
    docstring gives: Daily and Weekly need to coexist as independent rows
    per ticker, not parallel daily_/weekly_-prefixed columns on one row.

    Scoped to the union of every watchlist named W1 through W5 the
    nightly job reads, same as TechnicalEntrySignal -- a ticker on none of
    them simply has no rows here.

    support_zones_json/resistance_zones_json are plain-string JSON columns
    (a list of {price, cluster_size, formed_at} objects) -- this
    codebase's established convention for a JSON-shaped field (see
    TrendAnalysis.last_confirmed_swing_json/warning_swing_json above), not
    a native JSON column type, which doesn't exist anywhere else in this
    codebase either."""

    ticker: str = Field(primary_key=True)
    timeframe: str = Field(primary_key=True)  # "daily" | "weekly"
    last_price: float
    as_of: date
    support_zones_json: str
    resistance_zones_json: str
    source: str  # "fmp" | "yahoo"
    computed_at: datetime  # when the nightly job produced this row


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
    valuation.md §5) -- Risk-Free Rate and
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


class ReitDividendYieldConfig(SQLModel, table=True):
    """User-adjustable REIT dividend-yield bargain-reference threshold
    (valuation.md §3.3) -- editable via /settings, same lazy-seed
    get-or-create pattern as MoatScoreConfig (see
    helpers/reit_dividend_yield_config.py). Singleton row, keyed on a
    fixed `key` -- no region/per-ticker concept applies, just one global
    threshold."""

    key: str = Field(primary_key=True, default="default")
    threshold_pct: float
    updated_at: datetime


class LiquidityZoneConfig(SQLModel, table=True):
    """Per-timeframe Liquidity Zone (LP) detection settings -- editable via
    /settings, same lazy-seed get-or-create pattern as MoatScoreConfig/
    ReitDividendYieldConfig (see helpers/liquidity_zone_config.py).
    Singleton row, keyed on a fixed `key`. Daily and Weekly each get their
    own independent swing_bars/cluster_pct/num_zones -- deliberately not
    shared, since the two timeframes' lookback windows and typical price
    ranges call for different tuning. A change here only takes effect on
    the next nightly run (pipeline/nightly_liquidity_zone_calculation.py),
    not retroactively -- this feature has no live-recompute path the way
    Step 3's discount rate does."""

    key: str = Field(primary_key=True, default="default")
    daily_swing_bars: int
    daily_cluster_pct: float
    daily_num_zones: int
    weekly_swing_bars: int
    weekly_cluster_pct: float
    weekly_num_zones: int
    updated_at: datetime


class TickerBankCapitalMetrics(SQLModel, table=True):
    """Manually-entered CET1 (Common Equity Tier 1) ratio, plus an optional
    manual override for the NPL (non-performing loan) ratio Step 5 already
    computes automatically from raw XBRL tags for Bank tickers (see
    npl.py). No FMP source exists for CET1 at all (confirmed -- see
    CLAUDE.md's Step 5 CET1 deviation note), so it's manual-only, same
    non-FundamentalsCache treatment as TickerMoat/GrowthCatalystNote.
    npl_ratio_pct is an OVERRIDE only -- None means "no override, defer to
    the live compute_npl_ratio() result" (see step5_data.py); npl.py's own
    auto-compute path still runs every request regardless, to have a value
    available for pre-fill/fallback. Scoped to Bank tickers only, and
    further excluded for IBKR/HOOD (confirmed no customer deposit-taking
    business -- see step5_data.py's BANK_CET1_NPL_EXCLUDED_TICKERS), though
    nothing in this table's own schema enforces either restriction -- that's
    step5_data.py's job. Editable via the ticker page's Debt (Step 5) card,
    gated behind a confirm step in the UI, same pattern as TickerMoat's
    Economic Moat tab."""

    ticker: str = Field(primary_key=True)
    cet1_ratio_pct: float | None = None
    # Free-text filing-period label (e.g. "Q2 2026"), NOT a strict date --
    # matches npl.py's own NplResult.as_of convention.
    cet1_as_of: str | None = None
    npl_ratio_pct: float | None = None
    npl_as_of: str | None = None
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
    reasoning as FundamentalsCache.raw_json.

    watchlist_id is a discrete column, not folded into filters_json, since
    -- unlike the Fundamental/Technical filter state -- it needs real
    referential meaning: a saved view must survive the referenced
    Watchlist being renamed (looked up by id, not name) and must be
    cleaned up if it's deleted (see watchlists.py::delete_watchlist, which
    deletes any SavedScreenerFilter row referencing the watchlist in the
    same transaction as its WatchlistTicker cleanup -- no SQLite-level ON
    DELETE CASCADE, same reasoning as WatchlistTicker's own docstring).
    Nullable -- most saved views have no watchlist scoping at all."""

    __table_args__ = (UniqueConstraint("name", name="uq_saved_screener_filter_name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    universe: str
    sort_field: str
    sort_direction: str
    filters_json: str
    watchlist_id: int | None = Field(default=None, foreign_key="watchlist.id")
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
    sort_field: str = "overall_score"
    sort_direction: str = "desc"
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
    # "auto" / "custom" -- lifted straight from Step3Out.valuation_source via
    # the same get_summary() call valuation_verdict above already comes
    # from. None for any TickerScore row computed before this field existed
    # (see _add_missing_columns) rather than a fetch/scoring gap.
    valuation_source: str | None = None
    # Step 2's analyst-estimate CAGR % (EPS basis preferred, revenue
    # fallback -- see CLAUDE.md's Step 2 deviation note), lifted straight
    # from Step2Out.growth_rate. None when Step 2 has no usable projection.
    growth_rate: float | None = None
    computed_at: datetime
    # Ticker's own 5yr price return minus SPY's -- lifted straight from the
    # same get_summary() call market_cap/pe_ratio/beta above already come
    # from (see ticker_summary.py::_resolve_perf_vs_spy). status is
    # "outperform" / "underperform" / "match" / "no_data" / None (None only for SPY's
    # own row, or a row computed before this field existed -- see
    # _add_missing_columns).
    perf_5y_vs_spy_pct: float | None = None
    perf_5y_vs_spy_status: str | None = None
    # New, independent, read-only classification -- lifted straight from
    # SpeculativeGrowthOut.qualifies (see data/speculative_growth_data.py).
    # Never feeds Overall Assessment. None either for a ticker this gate
    # doesn't apply to at all (non-Standard company type) as much as for a
    # row computed before this field existed -- see _add_missing_columns --
    # both read as "no signal" for Screener/Watchlist filtering purposes.
    speculative_growth_qualifies: bool | None = None
    # Weinstein Stage Analysis, lifted straight from the matching
    # TrendAnalysis row (same ticker PK) via a plain session.get() read in
    # compute_ticker_score() -- not a live recomputation of the weekly
    # engine. None whenever no TrendAnalysis row exists yet for this ticker
    # (never computed, or computed before this field existed -- see
    # _add_missing_columns), same "no signal" convention as
    # speculative_growth_qualifies above. _since_date/_since_is_lower_bound/
    # _ma_slope_pct/_vs_ma_pct are carried along purely so the Screener
    # card's pill can show the same tooltip as the ticker-header pill
    # without a second query.
    weinstein_stage: str | None = None
    weinstein_stage_since_date: date | None = None
    weinstein_stage_since_is_lower_bound: bool | None = None
    weinstein_ma_slope_pct: float | None = None
    weinstein_vs_ma_pct: float | None = None
    # Reversal / Trend Continuation ("Pullback") status -- ported from the
    # Technical tab's own ReversalCard.tsx::reversalStatus /
    # TrendContinuationCard.tsx::resolutionStatus (see
    # analysis/trend_structure/technical_status.py), kept in each card's own
    # vocabulary rather than a forced shared enum. Computed in
    # compute_ticker_score() from the same TrendAnalysis sibling read as the
    # weinstein_* fields above, not a live recomputation of the swing/BOS
    # engine. None whenever no TrendAnalysis row exists yet, same "no
    # signal" convention as weinstein_stage.
    reversal_status: str | None = None  # "not_present" | "confirmed" | "confirmed_stale"
    pullback_status: str | None = None  # "no_pullback" | "pending" | "recovered" | "invalidated"
    # BB+RSI (2h) technical entry signal -- the DERIVED active state
    # (data/entry_signal_data.py::is_entry_signal_active on the matching
    # TechnicalEntrySignal row's fired_at, same session.get() sibling-read
    # pattern as weinstein_stage/trend_analysis above), not a raw stored
    # flag (there is no such flag -- see TechnicalEntrySignal.fired_at's
    # own comment). Computed once at this row's own compute_at time, same
    # nightly-snapshot staleness every other TickerScore field already has
    # -- not re-derived live per Screener page view. None for the
    # overwhelming majority of tickers, since this signal is only ever
    # computed for members of a watchlist named W1 through W5 (see
    # pipeline/nightly_entry_signal_calculation.py), not the full tracked
    # universe. A universe ticker on none of them reads None here
    # exactly the same way a row computed before this field existed would
    # (see _add_missing_columns) -- both mean "no signal," not an error.
    bb_rsi_entry_signal: bool | None = None
    # Warren (RSI/ADX/WVF, 2h) technical entry signal -- the DERIVED active
    # kind (data/warren_signal_data.py::warren_active_up_kind on the
    # matching signal_type="warren" TechnicalEntrySignal row's signal_kind,
    # same session.get() sibling-read pattern as bb_rsi_entry_signal
    # above): "blue_up" / "yellow_up" / "gray_up" when the ticker's latest
    # recorded event was that specific buy-side arrow with no sell since,
    # else None. Powers the Screener's 3-option (Blue/Yellow/Gray Up)
    # multi-select filter -- see warren_active_up_kind's own docstring for
    # why all three kinds are equally well-defined "currently active"
    # states, unlike an earlier version of this field that was a single
    # Blue+Yellow-only boolean excluding Gray Up as a selectable option
    # entirely. None for the overwhelming majority of tickers, same
    # W1-W5-only scoping as bb_rsi_entry_signal.
    warren_active_signal_kind: str | None = None
    # Max fired_at across every WarrenSignalEvent buy-side arrow (Blue/
    # Yellow/Gray Up) ever recorded for this ticker -- data/
    # warren_signal_data.py::last_buy_signal_fired_at, a genuine query
    # against WarrenSignalEvent rather than a copy of
    # TechnicalEntrySignal.fired_at, which holds the latest event of
    # EITHER direction and would misreport recency once a ticker's state
    # has flipped to a sell arrow since its last buy. Deliberately
    # independent of warren_active_signal_kind above and of the Screener
    # filter built on it -- always the combined Blue/Yellow/Gray Up
    # recency regardless of which kind(s) a user has filtered for. None
    # whenever no buy arrow has ever fired for this ticker (including
    # every ticker outside W1-W5, same as warren_active_signal_kind
    # above).
    warren_last_buy_fired_at: datetime | None = None


class TickerCustomValuation(SQLModel, table=True):
    """A user-saved, persistent override of Step 3's Auto Calculation --
    method + full parameter set for scoring.step3.run_manual_calculation
    (the same engine the stateless Manual Calculation panel already used).
    One row per ticker, no history/versioning: `is_active` decides whether
    this row or Auto Calculation is the ticker's current valuation source
    everywhere (Valuation tab, ticker header pill, Screener, Watchlist) --
    see data/step3_data.py::get_active_valuation, the single choke point
    that resolves this. Same non-FundamentalsCache, no-auth,
    manually-authored treatment as TickerMoat/TickerBankCapitalMetrics.

    parameters_json stores the *full* Step3ManualParams shape (all 13
    fields, nulls for whichever the chosen method doesn't use) rather than
    a sparse per-method subset -- run_manual_calculation has no default
    values on any parameter, so a sparse dict would raise TypeError on
    every read. Editable via the ticker page's Valuation tab (Custom
    Valuation panel)."""

    ticker: str = Field(primary_key=True)
    method: str  # DCF | DFCF | DNI | DNI_NORMALIZED | CF_NORMALIZED | FCF_NORMALIZED | PRICE_TO_BOOK | PSG
    parameters_json: str
    is_active: bool = False
    saved_at: datetime


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


class MomentumSnapshot(SQLModel, table=True):
    """One row per ticker per monthly Momentum run (see
    pipeline/monthly_momentum_snapshot.py, scoring/momentum.py) -- a 3-way
    composite price-momentum lens (3mo/6mo/12mo trailing return average)
    over Fathom's Moat-rated universe. Independent of Step 1-5/Overall
    Assessment scoring entirely -- a pure price signal, never fed back into
    it.

    Deliberately append-only, same convention as PriceTargetSnapshot above
    (not upserted-latest-only like TrendAnalysis/TickerScore): the whole
    point is to preserve every past month's full ranked list so the
    frontend's This month/Previous month toggle -- and any future
    historical-rank view -- can read prior snapshots directly rather than
    needing a recompute. `as_of_date` is the NYSE trading day the lookback
    windows were actually anchored to (see
    helpers/trading_calendar.py::resolve_month_end_anchor), not the
    (usually few-days-later) day the cron happened to run -- `computed_at`
    is that real run timestamp instead.

    `moat` is a snapshot of the rating AT COMPUTE TIME, not a live
    foreign-key read -- deliberately, so a since-changed Moat rating can
    never retroactively alter what a past month's ranked list actually
    showed. `company_name`/an Overall Assessment score are NOT stored here
    at all -- the API layer (data/momentum_data.py::get_momentum_snapshot)
    joins those live from TickerScore at request time instead, so the
    "for context only" Overall score shown next to a historical snapshot
    always reflects today's score, never a frozen one."""

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    as_of_date: date = Field(index=True)
    computed_at: datetime
    moat: str  # "wide_moat" | "narrow_moat" | "no_moat"
    return_3mo: float
    return_6mo: float
    return_12mo: float
    composite_score: float
    rank: int


class CronRunLog(SQLModel, table=True):
    """One row per cron job invocation, written by core.cron_health.cron_heartbeat
    -- deliberately append-only (no UniqueConstraint, no upsert), same
    pattern as PriceTargetSnapshot above, since a run history is the whole
    point: a "running" row with no finished_at past that job's expected
    cadence is itself a useful stuck/crashed signal, not just noise to
    overwrite. Built to close the blind spot where an uncaught exception in
    a cron script bypasses the script's own logging.FileHandler entirely
    and only ever reaches stderr/<job>_cron.log -- see
    core/cron_health.py."""

    id: int | None = Field(default=None, primary_key=True)
    job_name: str = Field(index=True)  # dotted module path, e.g. "pipeline.backup_db" -- matches crontab.txt's `-m` invocation exactly
    started_at: datetime
    finished_at: datetime | None = None
    status: str  # "running" | "success" | "failure"
    error_summary: str | None = None
