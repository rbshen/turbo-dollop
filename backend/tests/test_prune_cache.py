from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

import pandas as pd

import clients.shared_bars_cache as shared_bars_cache
import pipeline.prune_cache as prune_cache
from core.history_merge import INVALIDATED_AT
from core.models import FundamentalsCache, SharedBarsCache


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(prune_cache, "engine", engine)
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    monkeypatch.setattr(prune_cache, "LOG_PATH", tmp_path / "test_prune_cache.log")
    return engine


def _stub_tracked(monkeypatch, tracked, floor=1):
    """Pin the tracked set (the classifiers have their own tests) and lower the sanity floor for a tiny fixture."""
    monkeypatch.setattr(prune_cache, "_load_tracked_tickers", lambda session: set(tracked))
    monkeypatch.setattr(prune_cache, "MIN_TRACKED_TICKERS", floor)


def _remaining(engine):
    with Session(engine) as session:
        return {(r.ticker, r.statement_type) for r in session.exec(select(FundamentalsCache)).all()}


def _seed(session, ticker, statement_type, days_old):
    session.add(
        FundamentalsCache(
            ticker=ticker,
            statement_type=statement_type,
            period="annual",
            fetched_at=datetime.now() - timedelta(days=days_old),
            raw_json="[]",
        )
    )


def test_rows_older_than_retention_are_deleted(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {"KEEPER"})
    with Session(engine) as session:
        _seed(session, "OLDCO", "profile", days_old=200)
        _seed(session, "FRESHCO", "profile", days_old=1)
        session.commit()

    deleted = prune_cache.prune_cache(retention_days=180)

    assert deleted == 1
    with Session(engine) as session:
        remaining = {row.ticker for row in session.exec(select(FundamentalsCache)).all()}
    assert remaining == {"FRESHCO"}


def test_dry_run_reports_but_does_not_delete(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {"KEEPER"})
    with Session(engine) as session:
        _seed(session, "OLDCO", "profile", days_old=200)
        session.commit()

    deleted = prune_cache.prune_cache(retention_days=180, dry_run=True)

    assert deleted == 1
    with Session(engine) as session:
        remaining = session.exec(select(FundamentalsCache)).all()
    assert len(remaining) == 1  # nothing actually deleted


def test_nothing_to_delete_returns_zero(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {"KEEPER"})
    with Session(engine) as session:
        _seed(session, "FRESHCO", "profile", days_old=1)
        session.commit()

    assert prune_cache.prune_cache(retention_days=180) == 0


def test_main_falls_back_to_settings_cache_retention_days(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(prune_cache.settings, "cache_retention_days", 30)
    captured = {}

    def fake_prune_cache(retention_days, dry_run=False):
        captured["retention_days"] = retention_days
        return prune_cache.PruneResult(0, 0)

    monkeypatch.setattr(prune_cache, "prune_cache_result", fake_prune_cache)

    prune_cache.main(retention_days=None)

    assert captured["retention_days"] == 30


def test_main_explicit_retention_days_overrides_settings(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(prune_cache.settings, "cache_retention_days", 30)
    captured = {}

    def fake_prune_cache(retention_days, dry_run=False):
        captured["retention_days"] = retention_days
        return prune_cache.PruneResult(0, 0)

    monkeypatch.setattr(prune_cache, "prune_cache_result", fake_prune_cache)

    prune_cache.main(retention_days=90)

    assert captured["retention_days"] == 90


def _aged_universe(session):
    """200-day-old rows: tracked, untracked, an ETF, a delisted ticker and a non-ticker key."""
    _seed(session, "TRK", "income_statement", days_old=200)
    _seed(session, "UNT", "income_statement", days_old=200)
    _seed(session, "ETFX", "etf_info", days_old=200)
    _seed(session, "DELCO", "income_statement", days_old=200)
    _seed(session, "USD", "forex_rate", days_old=200)
    session.commit()


def _stub_classifiers(monkeypatch):
    monkeypatch.setattr(prune_cache, "MIN_TRACKED_TICKERS", 1)
    monkeypatch.setattr(
        prune_cache, "classify_known_tickers", lambda s: {"TRK": "index", "UNT": "untracked", "DELCO": "delisted", "BRW": "browsed"}
    )
    monkeypatch.setattr(prune_cache, "classify_etf_tickers", lambda s: {"ETFX": "system"})


def test_tracked_stock_and_etf_old_rows_kept_untracked_delisted_and_non_ticker_keys_deleted(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_classifiers(monkeypatch)
    with Session(engine) as session:
        _aged_universe(session)

    result = prune_cache.prune_cache_result(180)

    assert (result.deleted, result.kept_tracked, result.skipped_reason) == (3, 2, None)
    assert _remaining(engine) == {("TRK", "income_statement"), ("ETFX", "etf_info")}


def test_dry_run_count_equals_real_delete_count(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_classifiers(monkeypatch)
    with Session(engine) as session:
        _aged_universe(session)

    dry = prune_cache.prune_cache_result(180, dry_run=True)
    assert len(_remaining(engine)) == 5
    real = prune_cache.prune_cache_result(180)

    assert dry == real
    assert len(_remaining(engine)) == 5 - real.deleted


def test_deletes_in_chunks(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {"TRK"})
    monkeypatch.setattr(prune_cache, "DELETE_CHUNK", 7)
    with Session(engine) as session:
        for i in range(30):
            _seed(session, f"OLD{i}", "profile", days_old=200)
        _seed(session, "TRK", "profile", days_old=200)
        session.commit()

    assert prune_cache.prune_cache(180) == 30
    assert _remaining(engine) == {("TRK", "profile")}


def test_treasury_rates_ages_out_even_for_a_tracked_ticker(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {"TRK"})
    with Session(engine) as session:
        _seed(session, "TRK", "treasury_rates", days_old=200)
        _seed(session, "TRK", "income_statement", days_old=200)
        session.commit()

    assert prune_cache.prune_cache(180) == 1
    assert _remaining(engine) == {("TRK", "income_statement")}


def test_refresh_marked_row_is_skipped_for_an_untracked_ticker(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {"TRK"})
    with Session(engine) as session:
        session.add(
            FundamentalsCache(ticker="UNT", statement_type="income_statement", period="annual", fetched_at=INVALIDATED_AT, raw_json="[]")
        )
        session.commit()

    assert prune_cache.prune_cache(180) == 0
    assert _remaining(engine) == {("UNT", "income_statement")}


def _seed_bar(session, ticker, day):
    bars = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}, index=pd.DatetimeIndex([pd.Timestamp(day)]))
    shared_bars_cache._write_rows(session, ticker, "1d", bars, fetched_at=datetime.now())
    session.commit()


def _seed_old_bar(session):
    _seed_bar(session, "OLDBAR", datetime.now().date() - timedelta(days=6 * 365 + 40))


def _bars_left(engine):
    with Session(engine) as session:
        return len(session.exec(select(SharedBarsCache)).all())


def test_empty_tracked_set_deletes_nothing_and_bars_trim_still_runs(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, set())
    monkeypatch.setattr(prune_cache, "init_db", lambda: None)
    with Session(engine) as session:
        _seed(session, "UNT", "profile", days_old=400)
        _seed_old_bar(session)

    result, bars = prune_cache.main(retention_days=180)

    assert result.deleted == 0 and result.skipped_reason
    assert _remaining(engine) == {("UNT", "profile")}
    assert bars["1d"] == 1 and _bars_left(engine) == 0


def test_classifier_raising_deletes_nothing_and_bars_trim_still_runs(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(prune_cache, "MIN_TRACKED_TICKERS", 1)
    monkeypatch.setattr(prune_cache, "init_db", lambda: None)

    def boom(session):
        raise RuntimeError("classifier down")

    monkeypatch.setattr(prune_cache, "classify_known_tickers", boom)
    monkeypatch.setattr(prune_cache, "classify_etf_tickers", lambda s: {"ETFX": "system"})
    with Session(engine) as session:
        _seed(session, "UNT", "profile", days_old=400)
        _seed_old_bar(session)

    result, bars = prune_cache.main(retention_days=180)

    assert result.deleted == 0 and "RuntimeError" in result.skipped_reason
    assert _remaining(engine) == {("UNT", "profile")}
    assert bars["1d"] == 1


def test_tracked_set_below_the_floor_deletes_nothing(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {f"T{i}" for i in range(99)}, floor=100)
    with Session(engine) as session:
        _seed(session, "UNT", "profile", days_old=400)
        session.commit()

    result = prune_cache.prune_cache_result(180)

    assert result.deleted == 0 and "below floor" in result.skipped_reason
    assert _remaining(engine) == {("UNT", "profile")}


def test_tracked_set_at_the_floor_prunes(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_tracked(monkeypatch, {f"T{i}" for i in range(100)}, floor=100)
    with Session(engine) as session:
        _seed(session, "UNT", "profile", days_old=400)
        session.commit()

    assert prune_cache.prune_cache(180) == 1


def test_floor_constant_is_100():
    assert prune_cache.MIN_TRACKED_TICKERS == 100


def test_bars_retention_unchanged(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(prune_cache, "init_db", lambda: None)
    _stub_tracked(monkeypatch, {"TRK"})
    today = datetime.now().date()
    with Session(engine) as session:
        _seed_bar(session, "OLD", today - timedelta(days=6 * 365 + 40))
        _seed_bar(session, "NEW", today - timedelta(days=30))

    _, bars = prune_cache.main(retention_days=180)

    assert bars["1d"] == 1
    with Session(engine) as session:
        assert [b.ticker for b in session.exec(select(SharedBarsCache)).all()] == ["NEW"]
