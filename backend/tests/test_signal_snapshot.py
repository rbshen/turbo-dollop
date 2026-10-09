"""The daily signal log: data/signal_snapshot_data.py, pipeline/nightly_signal_snapshot.py and their cron wiring. Fresh in-memory engine
throughout (CLAUDE.md, "Ad-hoc reproduction scripts"): the job module's own `engine` is patched as well as the session the data layer gets."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

import pipeline.nightly_signal_snapshot as job
from core.cron_health import CRON_JOB_NAMES, CronRunContext
from core.models import FundamentalsCache, TickerScore, TickerSignalSnapshot, TickerView
from data.signal_snapshot_data import SnapshotResult, good_undervalued_since_for, write_daily_snapshot

DAY = date(2026, 10, 9)  # a Friday


@pytest.fixture
def engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(job, "engine", engine)
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "nightly_signal_snapshot.log")
    return engine


def track(session, ticker, overall="Pass", valuation="undervalued", stage="advance", **extra):
    session.add(TickerView(ticker=ticker, last_viewed_at=DAY, added_at=datetime(2026, 10, 1)))
    if overall == "no-row":
        # Known to the app (a cached profile) and tracked, but no score row has been computed for it yet.
        session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="[]"))
    else:
        session.add(
            TickerScore(
                ticker=ticker, overall_verdict=overall, valuation_verdict=valuation, weinstein_stage=stage,
                computed_at=datetime(2026, 10, 9, 3, 25), **extra,
            )
        )


def rows(engine):
    with Session(engine) as session:
        return {r.ticker: r for r in session.exec(select(TickerSignalSnapshot).order_by(TickerSignalSnapshot.ticker)).all()}


def test_writes_one_row_per_tracked_ticker_from_the_stored_values(engine):
    with Session(engine) as session:
        track(session, "AAA", "Strong Pass", "undervalued", "base")
        track(session, "BBB", "Pass with caution", "undervalued", "decline")
        track(session, "CCC", "Pass", "fair", "advance")
        track(session, "DDD", "Fail", "undervalued", "top")
        track(session, "EEE", None, None, None)
        track(session, "FFF", "no-row")
        session.add(TickerScore(ticker="ZZZ", overall_verdict="Pass", valuation_verdict="undervalued", computed_at=datetime.now()))  # not tracked
        session.commit()
        result = write_daily_snapshot(session, DAY)
    assert (result.universe, result.written, result.already_present, result.no_score) == (6, 5, 0, 1)
    got = rows(engine)
    assert set(got) == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    assert [got[t].good_and_undervalued for t in ("AAA", "BBB", "CCC", "DDD", "EEE")] == [True, True, False, False, False]
    assert (got["BBB"].overall_verdict, got["BBB"].valuation_verdict, got["BBB"].weinstein_stage) == ("Pass with caution", "undervalued", "decline")
    assert got["AAA"].snapshot_date == DAY and got["AAA"].score_computed_at == datetime(2026, 10, 9, 3, 25)
    assert got["EEE"].overall_verdict is None


def test_rerun_is_idempotent_and_never_updates_a_logged_row(engine):
    with Session(engine) as session:
        track(session, "AAA")
        track(session, "BBB")
        session.commit()
        first = write_daily_snapshot(session, DAY)
        score = session.get(TickerScore, "AAA")
        score.overall_verdict, score.valuation_verdict = "Fail", "overvalued"  # a later change the same day
        session.add(score)
        track(session, "CCC")  # a ticker that joined later the same day IS added by the re-run
        session.commit()
        second = write_daily_snapshot(session, DAY)
        third = write_daily_snapshot(session, DAY)
    assert (first.written, first.already_present) == (2, 0)
    assert (second.written, second.already_present) == (1, 2)
    assert (third.written, third.already_present) == (0, 3)
    got = rows(engine)
    assert len(got) == 3 and got["AAA"].overall_verdict == "Pass" and got["AAA"].good_and_undervalued is True  # first write wins


def test_a_new_day_appends_a_new_row(engine):
    with Session(engine) as session:
        track(session, "AAA")
        session.commit()
        write_daily_snapshot(session, DAY)
        write_daily_snapshot(session, DAY + timedelta(days=3))
        assert len(session.exec(select(TickerSignalSnapshot)).all()) == 2


def test_the_table_enforces_one_row_per_ticker_and_day(engine):
    with Session(engine) as session:
        session.add(TickerSignalSnapshot(ticker="AAA", snapshot_date=DAY))
        session.commit()
        session.add(TickerSignalSnapshot(ticker="AAA", snapshot_date=DAY))
        with pytest.raises(IntegrityError):
            session.commit()


def test_etfs_and_delisted_tickers_are_not_in_the_log(engine):
    with Session(engine) as session:
        track(session, "AAA")
        track(session, "DEAD", delisted_at=datetime(2026, 9, 1))
        track(session, "SPYX", is_etf=True)
        session.commit()
        write_daily_snapshot(session, DAY)
    assert set(rows(engine)) == {"AAA"}


def test_since_date_from_the_log_uses_the_smoothing_setting_and_nyse_sessions(engine):
    # Mon 5 Oct 2026 .. Fri 9 Oct: in, in, out, in, out   (all trading days)
    pattern = [True, True, False, True, False]
    with Session(engine) as session:
        for i, in_state in enumerate(pattern):
            session.add(
                TickerSignalSnapshot(
                    ticker="AAA", snapshot_date=date(2026, 10, 5) + timedelta(days=i), good_and_undervalued=in_state
                )
            )
        session.commit()
        assert good_undervalued_since_for(session, "aaa", smoothing_days=5) == date(2026, 10, 5)
        assert good_undervalued_since_for(session, "AAA", smoothing_days=1) is None  # the last day is out
        assert good_undervalued_since_for(session, "NONE", smoothing_days=5) is None


def test_weekend_snapshots_do_not_count_toward_the_smoothing_window(engine):
    with Session(engine) as session:
        for day, in_state in [(date(2026, 10, 8), True), (date(2026, 10, 9), False), (date(2026, 10, 10), False), (date(2026, 10, 11), False)]:
            session.add(TickerSignalSnapshot(ticker="AAA", snapshot_date=day, good_and_undervalued=in_state))
        session.commit()
        # Fri out = one out trading day; Sat and Sun do not count, so a 2-day window has not elapsed.
        assert good_undervalued_since_for(session, "AAA", smoothing_days=2) == date(2026, 10, 8)
        assert good_undervalued_since_for(session, "AAA", smoothing_days=1) is None


def test_job_main_writes_and_the_outcome_message(engine):
    with Session(engine) as session:
        track(session, "AAA")
        track(session, "BBB", "no-row")
        session.commit()
    result = job.main(DAY)
    run = CronRunContext()
    job.record_outcome(result, run)
    assert run.message == "1 written, 0 already logged, 1 skipped (no stored score)"
    again = CronRunContext()
    job.record_outcome(job.main(DAY), again)
    assert again.message == "0 written, 1 already logged, 1 skipped (no stored score)"


def test_job_fails_loudly_when_nothing_could_be_logged(engine):
    with Session(engine) as session:
        track(session, "AAA", "no-row")
        session.commit()
    with pytest.raises(RuntimeError, match="No snapshot row"):
        job.record_outcome(job.main(DAY), CronRunContext())
    job.record_outcome(SnapshotResult(DAY, 0, 0, 0, 0), CronRunContext())  # empty universe: fine


def test_job_is_a_registered_cron_job():
    assert "pipeline.nightly_signal_snapshot" in CRON_JOB_NAMES
