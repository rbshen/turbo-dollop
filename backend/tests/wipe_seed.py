"""Shared seeding helpers for the registry guard and the wipe job tests (not a test module)."""

from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from core.models import (
    CorporateEvent,
    CorporateEventFetch,
    EtfScreenerRow,
    FundamentalsCache,
    GrowthCatalystNote,
    IndexConstituent,
    LiquidityZoneAnalysis,
    LongHistoryBars,
    MomentumSnapshot,
    NewsCache,
    PriceTargetSnapshot,
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
    Watchlist,
    WatchlistTicker,
    WeinsteinSettings,
)
from data.ticker_data_registry import WIPE_TABLES, create_legacy_tables

NOW = datetime(2026, 11, 15, 12, 0)


def make_engine(tmp_path=None):
    """A fresh engine with every table plus the model-less legacy ones. A file DB when `tmp_path` is given (real
    locking, separate connections: what the apply tests need), otherwise in-memory."""
    if tmp_path is not None:
        engine = create_engine(f"sqlite:///{tmp_path / 'wipe.db'}", connect_args={"check_same_thread": False})
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    create_legacy_tables(engine)
    return engine


def seed_wipe_tables(engine, ticker: str, view_days_ago: float | None = None, now: datetime = NOW) -> None:
    """One row for `ticker` in EVERY WIPE table (TickerView only when `view_days_ago` is not None)."""
    with Session(engine) as s:
        s.add(EtfScreenerRow(ticker=ticker))
        s.add(TickerScore(ticker=ticker, computed_at=now))
        s.add(TrendAnalysis(ticker=ticker, computed_at=now))
        s.add(TickerLastClose(ticker=ticker, close=1.0, as_of_date=date(2026, 11, 13), fetched_at=now))
        s.add(TechnicalEntrySignal(ticker=ticker, signal_type="bb_rsi", timeframe="2h", source="t", as_of=now, computed_at=now))
        s.add(TechnicalEntrySignalEvent(ticker=ticker, signal_type="bb_rsi", timeframe="2h", fired_at=now, created_at=now))
        s.add(WarrenSignalEvent(ticker=ticker, timeframe="2h", signal_kind="buy", fired_at=now, created_at=now))
        s.add(
            LiquidityZoneAnalysis(
                ticker=ticker, timeframe="1d", last_price=1.0, as_of=now, support_zones_json="[]",
                resistance_zones_json="[]", source="t", computed_at=now,
            )
        )
        s.add(
            MomentumSnapshot(
                ticker=ticker, as_of_date=date(2026, 11, 1), computed_at=now, moat="wide_moat", return_3mo=1.0,
                return_6mo=1.0, return_12mo=1.0, composite_score=1.0, rank=1,
            )
        )
        s.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=now, raw_json="{}"))
        s.add(NewsCache(ticker=ticker, fetched_at=now, raw_json="[]"))
        s.add(
            SharedBarsCache(
                ticker=ticker, interval="1d", bar_time=datetime(2026, 11, 13), open=1, high=1, low=1, close=1, volume=1, fetched_at=now
            )
        )
        s.add(LongHistoryBars(ticker=ticker, bar_time=datetime(2026, 11, 13), open=1, high=1, low=1, close=1, volume=1, fetched_at=now))
        s.add(PriceTargetSnapshot(ticker=ticker, snapshot_date=date(2026, 11, 13), fetched_at=now))
        s.add(CorporateEvent(ticker=ticker, event_type="earnings", event_date=date(2026, 11, 1)))
        s.add(CorporateEventFetch(ticker=ticker, event_type="earnings", fetched_at=now))
        if view_days_ago is not None:
            s.add(TickerView(ticker=ticker, last_viewed_at=now - timedelta(days=view_days_ago)))
        s.commit()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO newssentimentcache (ticker, fetched_at, raw_json) VALUES (:t, :n, '{}')"),
            {"t": ticker, "n": now},
        )


def count_wipe_rows(engine, ticker: str) -> dict[str, int]:
    """Rows per WIPE table for `ticker` (raw, counting forex_rate rows too)."""
    out = {}
    with engine.connect() as conn:
        for entry in WIPE_TABLES:
            out[entry.name] = conn.execute(
                text(f'SELECT COUNT(*) FROM "{entry.name}" WHERE "{entry.key_column}" = :t'), {"t": ticker}
            ).scalar_one()
    return out


def add_protection(engine, kind: str, ticker: str, now: datetime = NOW) -> None:
    """Gives `ticker` one protecting row. kind: index:<name>, watchlist, moat, custom_valuation, bank_capital,
    growth_note, rs_benchmark."""
    with Session(engine) as s:
        if kind.startswith("index:"):
            s.add(IndexConstituent(index_name=kind.split(":", 1)[1], ticker=ticker, company_name="c", last_synced_at=now))
        elif kind == "watchlist":
            wl = Watchlist(name=f"L-{ticker}", created_at=now, updated_at=now)
            s.add(wl)
            s.commit()
            s.add(WatchlistTicker(watchlist_id=wl.id, ticker=ticker, added_at=now))
        elif kind == "moat":
            s.add(TickerMoat(ticker=ticker, moat="no_moat", updated_at=now))
        elif kind == "custom_valuation":
            s.add(TickerCustomValuation(ticker=ticker, method="DCF", parameters_json="{}", saved_at=now, is_active=False))
        elif kind == "bank_capital":
            s.add(TickerBankCapitalMetrics(ticker=ticker, updated_at=now))
        elif kind == "growth_note":
            s.add(GrowthCatalystNote(ticker=ticker, notes="why", updated_at=now))
        elif kind == "rs_benchmark":
            row = s.get(WeinsteinSettings, "default")
            if row is None:
                s.add(
                    WeinsteinSettings(
                        key="default", ma_length=30, ma_type="EMA", within_range_pct=5.0, slope_lookback=5,
                        breakout_volume_mult=2.0, volume_avg_length=50, rs_benchmark=ticker, rs_smoothing_length=52, updated_at=now,
                    )
                )
            else:
                row.rs_benchmark = ticker
                s.add(row)
        else:
            raise ValueError(kind)
        s.commit()
