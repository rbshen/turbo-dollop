import json
from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

import pipeline.nightly_fundamentals_fetch as nightly
import pipeline.stale_data_health_check as health_check
from core.models import (
    DiscountRateConfig,
    FundamentalsCache,
    SharedBarsCache,
    TickerScore,
    Watchlist,
    WatchlistTicker,
)
from pipeline.backfills.non_us_cleanup import run as cleanup_run
from pipeline.non_us_purge import find_non_us_tickers, purge_non_us_tickers

NOW = datetime(2026, 9, 26)


def _engine(monkeypatch=None, tmp_path=None):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    if monkeypatch is not None:
        monkeypatch.setattr(health_check, "engine", engine)
        monkeypatch.setattr(nightly, "engine", engine)
        monkeypatch.setattr(health_check, "LOG_PATH", tmp_path / "t.log")

        async def no_delisted(page, limit=100):
            return []

        monkeypatch.setattr(health_check.fmp_client, "get_delisted_companies", no_delisted)
    return engine


def _seed(engine, ticker: str, exchange: str | None):
    """A tracked ticker: a cached profile (with `exchange`, or none), a score row, a watchlist entry and a bar."""
    with Session(engine) as session:
        if exchange is not None:
            session.add(
                FundamentalsCache(
                    ticker=ticker,
                    statement_type="profile",
                    period="latest",
                    fetched_at=NOW,
                    raw_json=json.dumps([{"symbol": ticker, "exchange": exchange}]),
                )
            )
        session.add(TickerScore(ticker=ticker, computed_at=NOW))
        watchlist = session.exec(select(Watchlist)).first()
        if watchlist is None:
            watchlist = Watchlist(name="W1", created_at=NOW, updated_at=NOW)
            session.add(watchlist)
            session.commit()
            session.refresh(watchlist)
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=ticker, added_at=NOW))
        session.add(
            SharedBarsCache(
                ticker=ticker, interval="1d", bar_time=NOW, open=1, high=1, low=1, close=1, volume=1, fetched_at=NOW
            )
        )
        session.commit()


def _count(engine, table: str, ticker: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f'select count(*) from "{table}" where ticker = :t'), {"t": ticker}).scalar_one()


def _seed_mixed(engine):
    _seed(engine, "AAPL", "NASDAQ")
    _seed(engine, "TSM", "NYSE")  # a US-listed ADR -- must survive
    _seed(engine, "HBCYF", "OTC")  # OTC counts as US by decision
    _seed(engine, "0005.HK", "HKSE")
    _seed(engine, "MC.PA", None)  # no profile, dotted symbol


def test_detects_by_exchange_and_by_dotted_symbol_without_a_profile():
    engine = _engine()
    _seed_mixed(engine)
    with Session(engine) as session:
        assert find_non_us_tickers(session) == {"0005.HK": "HKSE", "MC.PA": None}


def test_purge_removes_every_table_for_non_us_and_keeps_us_adrs_idempotently():
    engine = _engine()
    _seed_mixed(engine)

    first = purge_non_us_tickers(engine)

    assert first["tickers"] == ["0005.HK", "MC.PA"]
    assert set(first["rows"]) >= {"tickerscore", "watchlistticker", "sharedbarscache"}
    for ticker in ("0005.HK", "MC.PA"):
        for table in ("tickerscore", "watchlistticker", "sharedbarscache", "fundamentalscache"):
            assert _count(engine, table, ticker) == 0
    for ticker in ("AAPL", "TSM", "HBCYF"):
        assert _count(engine, "tickerscore", ticker) == 1
        assert _count(engine, "sharedbarscache", ticker) == 1

    assert purge_non_us_tickers(engine) == {"tickers": [], "rows": {}, "refused": False}


def test_dry_run_deletes_nothing():
    engine = _engine()
    _seed_mixed(engine)

    result = purge_non_us_tickers(engine, dry_run=True)

    assert result["tickers"] == ["0005.HK", "MC.PA"]
    assert result["rows"]["tickerscore"] == 2
    assert _count(engine, "tickerscore", "0005.HK") == 1


def test_refuses_to_delete_when_the_hit_list_exceeds_the_safety_cap():
    # An exchange-name mismatch (e.g. FMP renaming "NYSE") would flag most of the universe.
    engine = _engine()
    _seed(engine, "AAPL", "NASDAQ")
    _seed(engine, "MSFT", "NASDAQ GLOBAL")
    _seed(engine, "JPM", "NYSE GLOBAL")

    result = purge_non_us_tickers(engine, max_fraction=0.02)

    assert result["refused"] is True
    assert result["rows"] == {}
    assert _count(engine, "tickerscore", "MSFT") == 1


def test_weekly_health_check_removes_a_non_us_ticker_and_reports_it(monkeypatch, tmp_path, capsys):
    engine = _engine(monkeypatch, tmp_path)
    for i in range(60):
        _seed(engine, f"US{i}", "NYSE")
    _seed(engine, "0700.HK", "HKSE")

    result = health_check.main(threshold_days=10)

    assert result["non_us"]["tickers"] == ["0700.HK"]
    assert _count(engine, "tickerscore", "0700.HK") == 0
    assert _count(engine, "tickerscore", "US0") == 1
    assert "Removed non-US tickers: 0700.HK" in capsys.readouterr().out


def test_cleanup_script_dry_run_then_real_run_then_idempotent():
    engine = _engine()
    _seed_mixed(engine)
    _seed(engine, "0941.HK", "HKSE")  # one of the known leftovers
    with Session(engine) as session:
        session.add(DiscountRateConfig(region="US", risk_free_rate=0.03, market_risk_premium=0.03, updated_at=NOW))
        session.add(DiscountRateConfig(region="HK", risk_free_rate=0.03, market_risk_premium=0.06, updated_at=NOW))
        session.commit()

    dry = cleanup_run(engine, dry_run=True)
    assert dry["discount_rate_rows_deleted"] == 1
    assert _count(engine, "tickerscore", "0941.HK") == 1

    real = cleanup_run(engine)
    assert real["discount_rate_rows_deleted"] == 1
    assert _count(engine, "tickerscore", "0941.HK") == 0
    assert _count(engine, "tickerscore", "AAPL") == 1
    with engine.connect() as conn:
        assert [r[0] for r in conn.execute(text("select region from discountrateconfig"))] == ["US"]

    assert cleanup_run(engine)["rows_deleted_by_table"] == {}
    assert cleanup_run(engine)["discount_rate_rows_deleted"] == 0
