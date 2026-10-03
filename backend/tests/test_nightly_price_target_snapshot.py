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

    monkeypatch.setattr(monthly, "load_us_price_target_universe", fail_if_queried)

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


def _result(written=0, no_data=0, etf_skipped=0, failed=0):
    return {
        "processed": written + no_data + failed, "written": written, "no_data": no_data,
        "etf_skipped": etf_skipped, "failed": failed, "failures": [],
    }


def test_run_where_every_ticker_failed_is_a_failure(monkeypatch):
    row = _heartbeat_row(monkeypatch, _result(failed=3))
    assert row.status == "failure"


def test_normal_run_is_success_with_summary(monkeypatch):
    row = _heartbeat_row(monkeypatch, _result(written=600, no_data=6, etf_skipped=10))
    assert row.status == "success"
    assert row.error_summary == "600 written, 6 no analyst data, 10 skipped (ETF), 0 failed"


def test_no_data_and_etf_skips_never_count_toward_the_failure_threshold(monkeypatch):
    # 100 no_data of 110 attempted would be 90% if counted; it must stay a success.
    row = _heartbeat_row(monkeypatch, _result(written=10, no_data=100, etf_skipped=50))
    assert row.status == "success"


def test_failures_at_or_above_five_percent_of_attempted_fail_the_run(monkeypatch):
    # 30 of 600 = 5.0% -> failure; 29 of 600 = 4.8% -> success.
    assert _heartbeat_row(monkeypatch, _result(written=570, failed=30)).status == "failure"
    row = _heartbeat_row(monkeypatch, _result(written=571, failed=29))
    assert row.status == "success"
    assert row.error_summary == "571 written, 0 no analyst data, 0 skipped (ETF), 29 failed"


def test_failed_run_message_keeps_the_counts(monkeypatch):
    row = _heartbeat_row(monkeypatch, _result(written=500, no_data=6, failed=100))
    assert row.status == "failure"
    assert "500 written, 6 no analyst data" in row.error_summary and "100 failed" in row.error_summary


# --- result classification and the ETF skip ----------------------------------


def _stub_responses(monkeypatch, responses):
    """`responses` maps ticker -> list (FMP body), or an Exception instance to raise."""

    async def fake(ticker):
        r = responses[ticker]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(monthly.fmp_client, "get_price_target_consensus", fake)
    monkeypatch.setattr(monthly.fmp_client, "min_request_interval", 0)


def test_results_are_classified_written_no_data_or_failed(monkeypatch, tmp_path):
    import httpx

    engine = _fresh_engine(monkeypatch, tmp_path)
    _stub_responses(monkeypatch, {
        "AAPL": [{"targetConsensus": 100.0, "targetHigh": 110.0, "targetLow": 90.0, "targetMedian": 100.0}],
        "ERIE": [],  # HTTP 200, empty body
        "NWS": {},  # empty dict body, same thing
        "ADP": httpx.HTTPStatusError("502 Bad Gateway", request=httpx.Request("GET", "http://x"), response=httpx.Response(502)),
        "SLOW": httpx.ReadTimeout("timed out"),
        "BAD": RuntimeError("boom"),
    })

    summary = asyncio.run(monthly.main(tickers=["AAPL", "ERIE", "NWS", "ADP", "SLOW", "BAD"]))

    assert (summary["written"], summary["no_data"], summary["failed"], summary["processed"]) == (1, 2, 3, 6)
    assert sorted(t for t, _ in summary["failures"]) == ["ADP", "BAD", "SLOW"]
    assert [r.ticker for r in _rows(engine)] == ["AAPL"]  # no all-null rows for the no_data tickers


def test_empty_body_is_cached_and_still_no_data_on_the_next_run_within_a_day(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    _stub_responses(monkeypatch, {"ERIE": []})
    first = asyncio.run(monthly.main(tickers=["ERIE"]))

    async def fail_if_called(ticker):
        raise AssertionError("1-day cache must serve the cached empty row")

    monkeypatch.setattr(monthly.fmp_client, "get_price_target_consensus", fail_if_called)
    second = asyncio.run(monthly.main(tickers=["ERIE"]))
    assert first["no_data"] == second["no_data"] == 1 and second["failed"] == 0


def test_group_off_mid_run_with_nothing_cached_is_a_failure_not_no_data(monkeypatch, tmp_path):
    # get_or_fetch returns None (no cached row, group not live): not an answer from FMP.
    _fresh_engine(monkeypatch, tmp_path)

    async def fake_get_or_fetch(*args, **kwargs):
        return None

    monkeypatch.setattr(monthly, "get_or_fetch", fake_get_or_fetch)
    summary = asyncio.run(monthly.main(tickers=["AAPL"]))
    assert (summary["no_data"], summary["failed"]) == (0, 1)


def test_run_universe_has_no_etf_since_the_cutover_so_none_is_left_to_skip(monkeypatch, tmp_path):
    # Cutover 2026-10-03: the tracked universe is the stock side, so the known-ETF filter in
    # load_price_target_run_universe now finds nothing to drop (it stays as a belt-and-braces guard).
    import json

    from core.models import TickerScore, TickerView

    engine = _fresh_engine(monkeypatch, tmp_path)
    now = datetime(2026, 10, 2)

    def profile(ticker, **flags):
        return FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=now, raw_json=json.dumps([{"exchange": "NASDAQ", **flags}]))

    with Session(engine) as session:
        session.add_all([
            profile("AAPL", isEtf=False, isFund=False),
            profile("QQQ", isEtf=True, isFund=False),  # ETF by cached profile
            profile("VTSAX", isEtf=False, isFund=True),  # fund by cached profile
            profile("TECL", isEtf=False, isFund=False),
        ])
        session.add(TickerScore(ticker="TECL", computed_at=now, is_etf=True))  # ETF by score row
        session.add_all([TickerView(ticker=t, last_viewed_at=datetime.now(), added_at=datetime.now(), added_source="user") for t in ("AAPL", "QQQ", "VTSAX", "TECL")])
        session.commit()
        monkeypatch.setattr(monthly, "_profile_exchanges", lambda tickers: {t: "NASDAQ" for t in tickers})
        assert monthly.load_price_target_run_universe(session) == (["AAPL"], 0)


def test_main_skips_etfs_from_the_default_universe_but_not_from_an_explicit_list(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(monthly, "load_price_target_run_universe", lambda session: (["AAPL"], 2))
    calls = _stub_fmp(monkeypatch, 100.0)

    summary = asyncio.run(monthly.main())
    assert (summary["written"], summary["etf_skipped"]) == (1, 2)
    assert calls == ["AAPL"]

    calls.clear()
    explicit = asyncio.run(monthly.main(tickers=["SPY"]))  # an explicit list bypasses the universe filter
    assert calls == ["SPY"] and explicit["etf_skipped"] == 0


def test_universe_is_us_listed_tracked_tickers_minus_delisted(monkeypatch, tmp_path):
    import json

    from core.models import TickerScore, TickerView

    engine = _fresh_engine(monkeypatch, tmp_path)
    now = datetime(2026, 9, 25)

    def profile(ticker, exchange):
        return FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=now, raw_json=json.dumps([{"exchange": exchange}]))

    with Session(engine) as session:
        session.add_all([
            profile("AAPL", "NASDAQ"),
            profile("TSM", "NYSE"),  # foreign domicile, US listing -> in
            profile("OXY", "NYSE"),
            profile("0005.HK", "HKSE"),  # non-US listing -> out
            profile("TWTR", "NYSE"),  # delisted-flagged -> out
        ])
        session.add(TickerScore(ticker="TWTR", computed_at=now, delisted_at=now))
        session.add_all([TickerView(ticker=t, last_viewed_at=datetime.now(), added_at=datetime.now(), added_source="user") for t in ("AAPL", "TSM", "OXY", "0005.HK", "TWTR")])
        session.commit()
        monkeypatch.setattr(monthly, "_profile_exchanges", lambda tickers: {"AAPL": "NASDAQ", "TSM": "NYSE", "OXY": "NYSE", "0005.HK": "HKSE", "TWTR": "NYSE"})
        assert monthly.load_us_price_target_universe(session) == ["AAPL", "OXY", "TSM"]
