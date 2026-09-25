import core.data_groups as _dg
import asyncio

from sqlmodel import SQLModel, create_engine

import pipeline.nightly_price_target_snapshot as monthly


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(monthly, "engine", engine)
    # main() calls configure_logging(LOG_PATH) with force=True, which
    # reconfigures the ROOT logger for the rest of this pytest process --
    # pointing it at a tmp_path file instead of the real production log
    # keeps test runs from polluting backend/logs/nightly_price_target_snapshot.log.
    monkeypatch.setattr(monthly, "LOG_PATH", tmp_path / "test_nightly_price_target_snapshot.log")
    return engine


def test_fmp_disabled_skips_the_run_before_any_fetch_or_universe_lookup(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    _dg.set_master(False)

    def fail_if_queried(*args, **kwargs):
        raise AssertionError("must not resolve the ticker universe while FMP is paused")

    monkeypatch.setattr(monthly, "load_universe_tickers", fail_if_queried)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("must not fetch price targets while FMP is paused")

    monkeypatch.setattr(monthly.fmp_client, "get_price_target_consensus", fail_if_called)

    summary = asyncio.run(monthly.main())  # tickers=None -- would normally resolve the full universe

    assert summary == {
        "processed": 0,
        "failed": 0,
        "calls_made": 0,
        "duration_seconds": 0.0,
        "failures": [],
        "skipped": True,
        "skip_reason": "skipped (FMP master switch off)",
    }


def test_fmp_disabled_skips_even_with_an_explicit_ticker_list(monkeypatch, tmp_path):
    # The guard is unconditional, same as nightly_fundamentals_fetch.py's
    # equivalent -- an explicit ticker list (e.g. from --tickers/--limit)
    # doesn't bypass it.
    _fresh_engine(monkeypatch, tmp_path)
    _dg.set_master(False)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("must not fetch price targets while FMP is paused")

    monkeypatch.setattr(monthly.fmp_client, "get_price_target_consensus", fail_if_called)

    summary = asyncio.run(monthly.main(tickers=["AAPL", "MSFT"]))

    assert summary["skipped"] is True
    assert summary["processed"] == 0


# --- daily job: upsert, tagging, heartbeat status ---------------------------

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import core.cron_health as cron_health  # noqa: E402
from core.cron_health import cron_heartbeat  # noqa: E402
from core.models import CronRunLog, FundamentalsCache, PriceTargetSnapshot  # noqa: E402
from pipeline.backfills.tag_price_target_methodology import tag_methodology  # noqa: E402


def _stub_fmp(monkeypatch, target):
    calls = []

    async def fake(ticker):
        calls.append(ticker)
        return [{"symbol": ticker, "targetConsensus": target, "targetHigh": target + 10, "targetLow": target - 10, "targetMedian": target}]

    monkeypatch.setattr(monthly.fmp_client, "get_price_target_consensus", fake)
    monkeypatch.setattr(monthly.fmp_client, "min_request_interval", 0)
    return calls


def _rows(engine):
    with Session(engine) as s:
        return s.exec(select(PriceTargetSnapshot).order_by(PriceTargetSnapshot.id)).all()


def test_rerun_same_day_updates_instead_of_duplicating(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_fmp(monkeypatch, 100.0)
    asyncio.run(monthly.main(tickers=["AAPL"]))
    assert [r.target_consensus for r in _rows(engine)] == [100.0]

    # New value from FMP, and the shared cache row aged past 1 day, so the re-run truly refetches.
    _stub_fmp(monkeypatch, 120.0)
    with Session(engine) as s:
        row = s.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "price_target_consensus")).one()
        row.fetched_at = datetime(2020, 1, 1)
        s.commit()
    asyncio.run(monthly.main(tickers=["AAPL"]))

    rows = _rows(engine)
    assert len(rows) == 1
    assert rows[0].target_consensus == 120.0
    assert rows[0].target_high == 130.0
    assert rows[0].methodology == "live_consensus"


def test_earlier_days_are_preserved_when_a_new_day_is_written(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_fmp(monkeypatch, 100.0)
    with Session(engine) as s:
        s.add(PriceTargetSnapshot(ticker="AAPL", snapshot_date=date(2026, 8, 31), target_consensus=1.0, fetched_at=datetime.now(), methodology="legacy_all_analysts"))
        s.commit()
    asyncio.run(monthly.main(tickers=["AAPL"]))
    rows = _rows(engine)
    assert [(r.methodology, r.target_consensus) for r in rows] == [("legacy_all_analysts", 1.0), ("live_consensus", 100.0)]


def test_job_shares_the_cache_row_with_tab_views(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    calls = _stub_fmp(monkeypatch, 100.0)
    asyncio.run(monthly.main(tickers=["AAPL"]))
    with Session(engine) as s:
        assert s.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "price_target_consensus")).one().ticker == "AAPL"
    asyncio.run(monthly.main(tickers=["AAPL"]))  # fresh cache -> no second FMP call
    assert calls == ["AAPL"]


def test_unique_index_rejects_a_duplicate_ticker_date(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as s:
        for _ in range(2):
            s.add(PriceTargetSnapshot(ticker="AAPL", snapshot_date=date(2026, 9, 26), fetched_at=datetime.now()))
        with pytest.raises(IntegrityError):
            s.commit()


def test_init_db_adds_the_unique_index_to_a_preexisting_table(monkeypatch):
    from sqlalchemy import create_engine as sa_create, inspect, text

    import core.db as db

    engine = sa_create("sqlite://")
    with engine.begin() as conn:  # the pre-change shape: no methodology column, no unique index
        conn.execute(text("CREATE TABLE pricetargetsnapshot (id INTEGER PRIMARY KEY, ticker VARCHAR NOT NULL, snapshot_date DATE NOT NULL, "
                          "target_consensus FLOAT, target_high FLOAT, target_low FLOAT, target_median FLOAT, fetched_at DATETIME NOT NULL)"))
    monkeypatch.setattr(db, "engine", engine)
    db._add_missing_columns()
    db._ensure_unique_indexes()
    db._ensure_unique_indexes()  # idempotent
    insp = inspect(engine)
    assert "methodology" in {c["name"] for c in insp.get_columns("pricetargetsnapshot")}
    assert any(i["unique"] and i["column_names"] == ["ticker", "snapshot_date"] for i in insp.get_indexes("pricetargetsnapshot"))


def test_migration_tags_legacy_and_live_rows_and_is_idempotent(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as s:
        s.add(PriceTargetSnapshot(ticker="AAPL", snapshot_date=date(2026, 7, 27), fetched_at=datetime(2026, 7, 27, 10, 0)))
        s.add(PriceTargetSnapshot(ticker="AAPL", snapshot_date=date(2026, 8, 31), fetched_at=datetime(2026, 9, 16, 10, 49)))
        s.add(PriceTargetSnapshot(ticker="MSFT", snapshot_date=date(2026, 8, 31), fetched_at=datetime(2026, 9, 16, 10, 50)))
        s.add(PriceTargetSnapshot(ticker="MSFT", snapshot_date=date(2026, 9, 1), fetched_at=datetime(2026, 9, 20, 1, 0)))  # neither cohort
        s.add(PriceTargetSnapshot(ticker="X", snapshot_date=date(2026, 8, 31), fetched_at=datetime(2026, 9, 16, 11, 0), methodology="live_consensus"))  # never overwritten
        s.commit()

    assert tag_methodology(engine) == {"legacy_all_analysts": 2, "live_consensus": 1}
    by_key = {(r.ticker, r.snapshot_date): r.methodology for r in _rows(engine)}
    assert by_key == {
        ("AAPL", date(2026, 7, 27)): "live_consensus",
        ("AAPL", date(2026, 8, 31)): "legacy_all_analysts",
        ("MSFT", date(2026, 8, 31)): "legacy_all_analysts",
        ("MSFT", date(2026, 9, 1)): None,
        ("X", date(2026, 8, 31)): "live_consensus",
    }
    assert tag_methodology(engine) == {"legacy_all_analysts": 0, "live_consensus": 0}


def _heartbeat_row(monkeypatch, result):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cron_health, "engine", engine)
    try:
        with cron_heartbeat("pipeline.nightly_price_target_snapshot") as run:
            monthly.record_outcome(result, run)
    except RuntimeError:
        pass
    with Session(engine) as s:
        return s.exec(select(CronRunLog)).one()


def test_gated_run_is_recorded_as_skipped_not_success(monkeypatch):
    row = _heartbeat_row(monkeypatch, {"processed": 0, "failed": 0, "skipped": True, "skip_reason": "skipped (group analyst_ratings disabled)"})
    assert row.status == "skipped"
    assert row.error_summary == "skipped (group analyst_ratings disabled)"


def test_run_where_every_ticker_failed_is_a_failure(monkeypatch):
    row = _heartbeat_row(monkeypatch, {"processed": 3, "failed": 3, "failures": []})
    assert row.status == "failure"


def test_normal_run_is_success_with_summary(monkeypatch):
    row = _heartbeat_row(monkeypatch, {"processed": 10, "failed": 1, "failures": []})
    assert row.status == "success"
    assert row.error_summary == "9 written, 1 failed"
