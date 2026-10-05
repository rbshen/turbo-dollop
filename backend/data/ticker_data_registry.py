"""The explicit registry of every table that carries a per-ticker key, and what the wipe does with it.
Spec: docs/specs/tracked-universe.md ("Planned: opt-in universe and wipe", not yet active) and
docs/universe-add-wipe-investigation-2026-10-03.md.

Three classes:

  WIPE        rows are deleted for a wipe candidate. `WIPE_TABLES` is the deletion ORDER: derived read-models
              first, caches next, `TickerView` LAST, so a run that dies half-way leaves a ticker that still has its
              `TickerView` row and is therefore still a candidate (retryable).
  PROTECTING  rows DEFINE a protection (index membership, watchlist entry, user-entered data). Never deleted by the
              wipe; a ticker with any such row is never a candidate.
  KEEP        has a per-ticker key but is not the wipe's to touch (shared, or keyed by seeds only).

`newssentimentcache` has no SQLModel class: it is a leftover of the Alpha Vantage News-Sentiment feature (added in
68dc559, removed entirely in c81e9b6, which deleted the model but not the live table, 3 rows). It is registered here
as a WIPE table with its own DDL (`legacy_ddl`) so a temp DB can be built with it and the guard sees it.

`unclassified_ticker_tables(engine)` is the guard: every table in a real schema with a ticker-like column
(name contains "ticker" or "symbol") must be classified here or in `NOT_A_TICKER_KEY` (a documented non-key
column). `tests/test_ticker_data_registry.py` fails on any other table; the wipe job refuses `--apply` on one.

This module imports only `core.models`: `data/tracked_universe.py` (the candidate logic) imports it, never the
other way round."""

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from core.models import (
    CorporateEvent,
    CorporateEventFetch,
    EtfMomentumSnapshot,
    EtfScreenerRow,
    FundamentalsCache,
    GrowthCatalystNote,
    IndexConstituent,
    LiquidityZoneAnalysis,
    LongHistoryBars,
    MomentumSnapshot,
    NewsCache,
    PriceTargetSnapshot,
    SectorEtfReturn,
    SharedBarsCache,
    TechnicalEntrySignal,
    TechnicalEntrySignalEvent,
    TickerBankCapitalMetrics,
    TickerCustomValuation,
    TickerLastClose,
    TickerMoat,
    TickerScore,
    TickerView,
    TrendAnalysis,
    WarrenSignalEvent,
    WatchlistTicker,
)


class TableClass(str, Enum):
    WIPE = "wipe"
    PROTECTING = "protecting"
    KEEP = "keep"


@dataclass(frozen=True)
class TickerTable:
    name: str
    key_column: str
    table_class: TableClass
    note: str
    # SQL predicate (on this table's own columns) for rows the wipe must NEVER touch even for a candidate.
    keep_where: str | None = None
    # For a table with no SQLModel class (not in SQLModel.metadata): its CREATE TABLE, so a temp DB can have it.
    legacy_ddl: str | None = None
    # PROTECTING only: True when the rows are entered by the owner (feeds `load_manual_data_tickers`).
    user_entered: bool = False


def _t(model, table_class: TableClass, note: str, **kwargs) -> TickerTable:
    return TickerTable(model.__tablename__, "ticker", table_class, note, **kwargs)


# Order matters for WIPE entries (see the module docstring); TickerView is last (a test pins it).
_ORDERED: tuple[TickerTable, ...] = (
    # --- WIPE: derived read-models and per-ticker results -----------------------------------------------------
    _t(EtfScreenerRow, TableClass.WIPE, "ETFs screener read-model (the nightly ETF job also prunes it)"),
    _t(TickerScore, TableClass.WIPE, "Screener/Watchlist score row; also carries the delisted_at flag"),
    _t(TrendAnalysis, TableClass.WIPE, "Weinstein stage row"),
    _t(TickerLastClose, TableClass.WIPE, "last official close (header price fallback)"),
    _t(TechnicalEntrySignal, TableClass.WIPE, "BB+RSI / Warren live reading (monitored watchlists only)"),
    _t(TechnicalEntrySignalEvent, TableClass.WIPE, "BB+RSI / Warren signal events (monitored watchlists only)"),
    _t(WarrenSignalEvent, TableClass.WIPE, "Warren signal events (monitored watchlists only)"),
    _t(LiquidityZoneAnalysis, TableClass.WIPE, "Liquidity Zone analysis (monitored watchlists only)"),
    _t(
        MomentumSnapshot,
        TableClass.WIPE,
        "Moat-rated tickers only, and a Moat protects: a candidate never has rows. Listed as WIPE for orphan cleanup",
    ),
    # --- WIPE: caches ------------------------------------------------------------------------------------------
    _t(
        FundamentalsCache,
        TableClass.WIPE,
        "every FMP statement type; the forex_rate rows are keyed EURUSD, CADUSD... (not tickers) and are never touched",
        keep_where="statement_type = 'forex_rate'",
    ),
    _t(NewsCache, TableClass.WIPE, "short-TTL news cache"),
    TickerTable(
        "newssentimentcache",
        "ticker",
        TableClass.WIPE,
        "legacy: Alpha Vantage News-Sentiment (feature removed in c81e9b6, model deleted, live table left behind)",
        legacy_ddl=(
            "CREATE TABLE newssentimentcache (ticker VARCHAR NOT NULL, fetched_at DATETIME NOT NULL, "
            "raw_json VARCHAR NOT NULL, PRIMARY KEY (ticker))"
        ),
    ),
    _t(SharedBarsCache, TableClass.WIPE, "shared daily/60m bars cache (the largest table)"),
    _t(LongHistoryBars, TableClass.WIPE, "on-demand ~10-year daily history"),
    _t(PriceTargetSnapshot, TableClass.WIPE, "nightly price-target snapshots (history that cannot be re-created)"),
    _t(CorporateEvent, TableClass.WIPE, "earnings/dividend/split cache (its nightly job is disabled: not rebuilt by cron)"),
    _t(CorporateEventFetch, TableClass.WIPE, "per-(ticker, event_type) last-fetch marker for CorporateEvent"),
    # --- WIPE: the state itself, last ---------------------------------------------------------------------------
    _t(TickerView, TableClass.WIPE, "the last-touch clock; deleted last so a half-done wipe stays retryable"),
    # --- PROTECTING ---------------------------------------------------------------------------------------------
    _t(IndexConstituent, TableClass.PROTECTING, "member of any index (sp500, nasdaq, dow, ... any index_name)"),
    _t(WatchlistTicker, TableClass.PROTECTING, "on any watchlist, monitored or not"),
    _t(TickerMoat, TableClass.PROTECTING, "owner-entered Economic Moat rating", user_entered=True),
    _t(TickerCustomValuation, TableClass.PROTECTING, "owner-saved custom valuation, active or not", user_entered=True),
    _t(TickerBankCapitalMetrics, TableClass.PROTECTING, "owner-entered CET1 / NPL override", user_entered=True),
    _t(GrowthCatalystNote, TableClass.PROTECTING, "owner-curated growth catalyst note", user_entered=True),
    # --- KEEP ---------------------------------------------------------------------------------------------------
    _t(
        EtfMomentumSnapshot,
        TableClass.KEEP,
        "frozen monthly ETF momentum rankings (a past month's full ranked list; wiping an ETF would rewrite its ranks)",
    ),
    _t(SectorEtfReturn, TableClass.KEEP, "11 sector ETFs only, all ETF_SEED_TICKERS (protected as seeds)"),
)

REGISTRY: dict[str, TickerTable] = {entry.name: entry for entry in _ORDERED}
WIPE_TABLES: tuple[TickerTable, ...] = tuple(e for e in _ORDERED if e.table_class is TableClass.WIPE)
PROTECTING_TABLES: tuple[TickerTable, ...] = tuple(e for e in _ORDERED if e.table_class is TableClass.PROTECTING)
LEGACY_TABLES: tuple[TickerTable, ...] = tuple(e for e in _ORDERED if e.legacy_ddl)

# The user-entered per-ticker models behind `load_manual_data_tickers` (the single list; the loader reads it).
MANUAL_DATA_MODELS = (TickerMoat, TickerCustomValuation, TickerBankCapitalMetrics, GrowthCatalystNote)

# The short reason label each user-entered table gives in the universe status API ("manual:moat").
MANUAL_DATA_LABELS: dict[str, str] = {
    "tickermoat": "moat",
    "tickercustomvaluation": "custom_valuation",
    "tickerbankcapitalmetrics": "bank_capital",
    "growthcatalystnote": "growth_note",
}

# Columns whose name looks ticker-like but are not a per-ticker key: (table, column) -> why.
NOT_A_TICKER_KEY: dict[tuple[str, str], str] = {
    ("marketbreadthgatelog", "missing_tickers_json"): "a capped sample of ticker names in a per-universe run log row",
}


def _is_ticker_like(column: str) -> bool:
    lowered = column.lower()
    return "ticker" in lowered or "symbol" in lowered


def unclassified_ticker_tables(engine: Engine) -> list[str]:
    """Tables of the schema `engine` points at that have a ticker-like column but are neither registered nor a
    documented non-key. Reads `sqlite_master`/PRAGMA only (writes nothing). Empty list = the registry is complete."""
    inspector = inspect(engine)
    unclassified = []
    for table in sorted(inspector.get_table_names()):
        if table in REGISTRY:
            continue
        for column in inspector.get_columns(table):
            if _is_ticker_like(column["name"]) and (table, column["name"]) not in NOT_A_TICKER_KEY:
                unclassified.append(f"{table}.{column['name']}")
    return unclassified


def create_legacy_tables(engine: Engine) -> None:
    """Creates the model-less legacy tables (test helper: a temp DB built from SQLModel metadata lacks them)."""
    with engine.begin() as conn:
        for entry in LEGACY_TABLES:
            conn.exec_driver_sql(entry.legacy_ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))


def metadata_ticker_tables() -> list[str]:
    """Model-backed tables with a ticker-like column (what `SQLModel.metadata` alone knows about)."""
    return sorted(
        table.name
        for table in SQLModel.metadata.sorted_tables
        if any(_is_ticker_like(column.name) for column in table.columns)
    )
