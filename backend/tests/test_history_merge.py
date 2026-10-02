"""History protection (core/history_merge.py, docs/specs/fmp-data-and-bar-cache.md "History protection"): a shorter,
empty or error answer from FMP must never leave a cached history shorter, a restated period must still update, and a
clamp is logged once per ticker per run and counted. Every test uses its own in-memory engine."""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import core.data_groups as dg
import pipeline.nightly_fundamentals_fetch as nightly
import pipeline.prune_cache as prune_cache
import pipeline.refresh as refresh
from clients.shared_bars_cache import DAILY_INTERVAL, INTRADAY_INTERVAL, _write_rows
from core.cache import force_fetch, get_or_fetch, get_or_fetch_earnings_aware
from core.cron_health import CronRunContext
from core.history_merge import HISTORY_KEYS, INVALIDATED_AT, SNAPSHOT_STATEMENT_TYPES, history_clamps, merge_history
from core.models import FundamentalsCache, SharedBarsCache


def fy_rows(first_year: int, last_year: int, **extra) -> list[dict]:
    """Annual rows newest first, like FMP: one per year, `date` = the fiscal year end."""
    return [{"date": f"{y}-12-31", "fiscalYear": str(y), "period": "FY", "revenue": float(y), **extra} for y in range(last_year, first_year - 1, -1)]


@pytest.fixture(autouse=True)
def _fresh_tracker():
    history_clamps.reset()
    yield
    history_clamps.reset()


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(engine, ticker, statement_type, period, payload, fetched_at=None):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker, statement_type=statement_type, period=period,
                fetched_at=fetched_at or datetime.now() - timedelta(days=30), raw_json=json.dumps(payload),
            )
        )
        session.commit()


def _stored(engine, ticker, statement_type, period) -> FundamentalsCache:
    with Session(engine) as session:
        return session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == ticker, FundamentalsCache.statement_type == statement_type,
                FundamentalsCache.period == period,
            )
        ).one()


def _refresh(engine, ticker, statement_type, period, payload, earnings_aware=True):
    async def fetch_fn():
        return payload

    async def run():
        with Session(engine) as session:
            if earnings_aware:
                return await get_or_fetch_earnings_aware(session, ticker, statement_type, period, fetch_fn, 7, None)
            return await get_or_fetch(session, ticker, statement_type, period, fetch_fn, 7)

    return asyncio.run(run())


# --- the pure rule ----------------------------------------------------------------------------------------------


def test_a_response_clamped_from_10_to_5_rows_keeps_the_older_cached_history():
    cached = fy_rows(2016, 2025)
    new = fy_rows(2021, 2026)[:5]  # FMP answers 2022..2026 only: a new year plus four overlapping ones
    merge = merge_history(cached, new)
    years = [r["fiscalYear"] for r in merge.rows]
    assert years == [str(y) for y in range(2026, 2016, -1)]  # 10 rows, newest first, the window rolled by one year
    assert len(merge.rows) == len(cached)  # never shorter
    assert merge.clamped and merge.action == "merge"
    assert (merge.cached_count, merge.new_count, merge.oldest_cached, merge.oldest_new) == (10, 5, "2016-12-31", "2022-12-31")


def test_a_clamp_with_no_new_period_keeps_every_cached_row_and_the_shape():
    cached = fy_rows(2016, 2025)
    merge = merge_history(cached, [dict(r) for r in cached[:5]])
    assert merge.rows == cached  # same rows, same order, same dict shape
    assert merge.clamped


def test_a_full_length_response_is_stored_exactly_as_returned():
    cached = fy_rows(2016, 2025)
    new = fy_rows(2017, 2026)
    merge = merge_history(cached, new)
    assert merge.rows == new and merge.action == "replace" and not merge.clamped


@pytest.mark.parametrize("body", [[], None, {}, {"Error Message": "Limit Reach"}, "oops", [None, 3]])
def test_an_empty_null_error_or_non_list_body_never_replaces_a_cached_row(body):
    cached = fy_rows(2016, 2025)
    merge = merge_history(cached, body)
    assert merge.rows == cached and merge.action == "kept_cached" and merge.empty_kept and not merge.clamped


def test_a_restated_period_replaces_the_cached_row_for_that_period():
    cached = fy_rows(2016, 2025)
    restated = {"date": "2023-12-31", "fiscalYear": "2023", "period": "FY", "revenue": 999.0}
    merge = merge_history(cached, [fy_rows(2025, 2025)[0], restated])
    by_year = {r["fiscalYear"]: r for r in merge.rows}
    assert by_year["2023"]["revenue"] == 999.0
    assert len(merge.rows) == 10 and by_year["2016"]["revenue"] == 2016.0  # old periods kept
    assert [r["fiscalYear"] for r in merge.rows] == [str(y) for y in range(2025, 2015, -1)]


def test_no_cached_row_stores_the_new_answer_even_when_it_is_empty():
    assert merge_history(None, fy_rows(2021, 2025)).rows == fy_rows(2021, 2025)
    assert merge_history(None, []).rows == [] and merge_history(None, []).action == "replace"
    assert merge_history([], fy_rows(2024, 2025)).rows == fy_rows(2024, 2025)  # a cached empty list holds nothing to protect


def test_a_young_company_that_gains_a_year_just_grows():
    merge = merge_history(fy_rows(2023, 2025), fy_rows(2023, 2026))
    assert len(merge.rows) == 4 and not merge.clamped


def test_rows_without_a_date_fall_back_to_never_shorter():
    cached = [{"x": i} for i in range(10)]
    assert merge_history(cached, [{"x": 1}] * 5).rows == cached
    longer = [{"x": i} for i in range(11)]
    assert merge_history(cached, longer).rows == longer


def test_quarterly_and_annual_keys_are_independent(engine):
    annual, quarterly = fy_rows(2016, 2025), [{"date": f"{y}-{m:02d}-30", "period": "Q"} for y in (2025, 2024, 2023) for m in (12, 9, 6, 3)][:12]
    _seed(engine, "AAA", "income_statement", "annual", annual)
    _seed(engine, "AAA", "income_statement", "quarterly", quarterly)
    _refresh(engine, "AAA", "income_statement", "quarterly", quarterly[:4])  # quarterly clamped to 4 rows
    _refresh(engine, "AAA", "income_statement", "annual", fy_rows(2016, 2025))  # annual unchanged
    assert json.loads(_stored(engine, "AAA", "income_statement", "quarterly").raw_json) == quarterly
    assert json.loads(_stored(engine, "AAA", "income_statement", "annual").raw_json) == annual


# --- through the cache layer -------------------------------------------------------------------------------------


def test_a_clamped_refresh_stores_and_returns_the_merged_row(engine):
    _seed(engine, "AAPL", "income_statement", "annual", fy_rows(2016, 2025))
    returned = _refresh(engine, "AAPL", "income_statement", "annual", fy_rows(2022, 2026))
    stored = json.loads(_stored(engine, "AAPL", "income_statement", "annual").raw_json)
    assert returned == stored and len(stored) == 10
    assert [r["fiscalYear"] for r in stored][:2] == ["2026", "2025"]
    assert stored[-1]["fiscalYear"] == "2017"
    assert _stored(engine, "AAPL", "income_statement", "annual").fetched_at > datetime.now() - timedelta(minutes=1)


@pytest.mark.parametrize("body", [[], {"Error Message": "x"}, None])
def test_an_empty_or_error_body_keeps_the_cached_rows_but_stamps_the_attempt(engine, body):
    cached = fy_rows(2016, 2025)
    _seed(engine, "AAPL", "balance_sheet_statement", "annual", cached)
    returned = _refresh(engine, "AAPL", "balance_sheet_statement", "annual", body)
    row = _stored(engine, "AAPL", "balance_sheet_statement", "annual")
    assert returned == cached and json.loads(row.raw_json) == cached
    assert row.fetched_at > datetime.now() - timedelta(minutes=1)  # recorded like today, so no re-fetch storm
    assert history_clamps.empty_kept_tickers() == 1 and history_clamps.clamped_tickers() == 0


def test_a_ticker_with_no_cached_row_is_written_as_before_even_if_empty(engine):
    assert _refresh(engine, "NEW", "income_statement", "annual", []) == []
    assert json.loads(_stored(engine, "NEW", "income_statement", "annual").raw_json) == []
    assert _refresh(engine, "NEW2", "income_statement", "annual", fy_rows(2023, 2025)) == fy_rows(2023, 2025)
    assert history_clamps.clamped_tickers() == 0 and history_clamps.empty_kept_tickers() == 0


def test_get_or_fetch_and_force_fetch_use_the_same_rule(engine):
    _seed(engine, "KO", "key_metrics", "annual", fy_rows(2016, 2025))
    assert len(_refresh(engine, "KO", "key_metrics", "annual", fy_rows(2023, 2026), earnings_aware=False)) == 10

    async def fetch_fn():
        return []

    async def run():
        with Session(engine) as session:
            return await force_fetch(session, "KO", "key_metrics", "annual", fetch_fn)

    assert len(asyncio.run(run())) == 10  # force_fetch can no longer wipe a history row with an empty answer


def test_a_snapshot_key_is_still_overwritten_wholesale(engine):
    _seed(engine, "KO", "profile", "latest", [{"companyName": "old"}])
    assert _refresh(engine, "KO", "profile", "latest", [], earnings_aware=False) == []
    assert json.loads(_stored(engine, "KO", "profile", "latest").raw_json) == []
    _seed(engine, "KO", "earnings", "latest", [{"date": "2026-01-01"}] * 3)
    assert _refresh(engine, "KO", "earnings", "latest", [{"date": "2026-02-01"}]) == [{"date": "2026-02-01"}]  # not merged: schedule rows go stale


def test_a_clamp_is_logged_once_per_ticker_per_run_and_counted(engine, caplog):
    for key in ("income_statement", "cash_flow_statement", "balance_sheet_statement"):
        _seed(engine, "AAPL", key, "annual", fy_rows(2016, 2025))
    _seed(engine, "MSFT", "income_statement", "annual", fy_rows(2016, 2025))
    _seed(engine, "KO", "income_statement", "annual", fy_rows(2016, 2025))
    with caplog.at_level(logging.WARNING, logger="core.history_merge"):
        for key in ("income_statement", "cash_flow_statement", "balance_sheet_statement"):
            _refresh(engine, "AAPL", key, "annual", fy_rows(2021, 2025))  # three clamped keys, one ticker
        _refresh(engine, "MSFT", "income_statement", "annual", fy_rows(2021, 2025))
        _refresh(engine, "KO", "income_statement", "annual", fy_rows(2016, 2025))  # full length: not a clamp
    lines = [r.getMessage() for r in caplog.records if "History clamped" in r.getMessage()]
    assert len(lines) == 2 and sum("AAPL" in line for line in lines) == 1  # AAPL once, MSFT once, KO never
    assert history_clamps.clamped_tickers() == 2
    history_clamps.reset()
    assert history_clamps.clamped_tickers() == 0  # a new run starts from zero


def test_every_cached_statement_type_is_either_history_or_snapshot():
    history = {t for t, _ in HISTORY_KEYS}
    assert history.isdisjoint(SNAPSHOT_STATEMENT_TYPES)
    assert history | SNAPSHOT_STATEMENT_TYPES == set(dg.STATEMENT_TYPE_GROUP), (
        "a new cached statement type must be added to core/history_merge.py HISTORY_KEYS or SNAPSHOT_STATEMENT_TYPES"
    )


# --- the nightly job's message ------------------------------------------------------------------------------------


def test_fundamentals_message_reports_clamps_without_turning_red():
    run = CronRunContext()
    result = {"processed": 587, "failed": 2, "calls_made": 2626, "duration_seconds": 2670.0}
    nightly.record_outcome({**result, "history_clamped": 587, "history_empty_kept": 0}, run)  # every ticker clamped: still green
    assert run.message == "585 refreshed, 2 failed, 2,626 FMP calls, 44.5 min, 587 history-clamped"
    run = CronRunContext()
    nightly.record_outcome({**result, "history_clamped": 3, "history_empty_kept": 12}, run)
    assert run.message.endswith(", 3 history-clamped, 12 empty-body kept")
    run = CronRunContext()
    nightly.record_outcome(result, run)
    assert "history" not in run.message  # absent when zero


def test_the_nightly_run_resets_and_reports_the_tracker(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly, "engine", engine)
    monkeypatch.setattr(nightly, "LOG_PATH", tmp_path / "nightly.log")
    history_clamps.record_clamp("STALE", "income_statement/annual", "left over from before the run")

    async def fake_refresh(ticker):
        if ticker == "AAPL":
            history_clamps.record_clamp(ticker, "income_statement/annual", "clamped")
            history_clamps.record_clamp(ticker, "ratios/annual_10y", "clamped")
        if ticker == "MSFT":
            history_clamps.record_empty_kept(ticker, "income_statement/annual", "empty")

    monkeypatch.setattr(nightly, "_refresh_one_ticker", fake_refresh)
    result = asyncio.run(nightly.main(["AAPL", "MSFT", "KO"]))
    assert result["history_clamped"] == 1 and result["history_empty_kept"] == 1 and result["failed"] == 0


# --- Refresh button and prune --------------------------------------------------------------------------------------


def test_refresh_keeps_history_rows_stale_instead_of_deleting_them(engine, monkeypatch):
    monkeypatch.setattr(refresh, "engine", engine)
    cached = fy_rows(2016, 2025)
    _seed(engine, "AAPL", "income_statement", "annual", cached, fetched_at=datetime.now())
    _seed(engine, "AAPL", "profile", "latest", [{"companyName": "Apple"}], fetched_at=datetime.now())
    result = refresh.clear_ticker_cache("AAPL")
    assert result.cleared_entries == 2 and result.statement_types == ["income_statement", "profile"]
    with Session(engine) as session:
        rows = session.exec(select(FundamentalsCache)).all()
    assert [(r.statement_type, r.fetched_at) for r in rows] == [("income_statement", INVALIDATED_AT)]

    # the next fetch re-fetches (stale to both freshness rules even right after an earnings date) and merges
    calls = []

    async def fetch_fn():
        calls.append(1)
        return fy_rows(2022, 2025)  # a clamped answer

    async def run(most_recent_earnings: date | None):
        with Session(engine) as session:
            return await get_or_fetch_earnings_aware(session, "AAPL", "income_statement", "annual", fetch_fn, 7, most_recent_earnings)

    assert len(asyncio.run(run(date.today() - timedelta(days=1)))) == 10  # inside the 2-day post-earnings buffer
    assert calls == [1]


def test_prune_never_deletes_a_row_a_refresh_marked_stale(engine, monkeypatch):
    monkeypatch.setattr(prune_cache, "engine", engine)
    _seed(engine, "AAA", "income_statement", "annual", fy_rows(2016, 2025), fetched_at=INVALIDATED_AT)
    _seed(engine, "BBB", "income_statement", "annual", fy_rows(2016, 2025), fetched_at=datetime.now() - timedelta(days=400))
    assert prune_cache.prune_cache(180) == 1
    with Session(engine) as session:
        assert [r.ticker for r in session.exec(select(FundamentalsCache)).all()] == ["AAA"]


# --- bars (SharedBarsCache replace path) ----------------------------------------------------------------------------


def _bar_frame(first: date, last: date, close=lambda d: 100.0) -> pd.DataFrame:
    index = pd.bdate_range(first, last)
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": [close(d.date()) for d in index], "volume": 1000}, index=index
    )


def _span(engine, interval=DAILY_INTERVAL):
    with Session(engine) as session:
        rows = session.exec(select(SharedBarsCache.bar_time).where(SharedBarsCache.interval == interval)).all()
    return (min(rows).date(), max(rows).date(), len(rows)) if rows else None


TODAY = date(2026, 10, 1)


def _write(engine, df, interval=DAILY_INTERVAL, **kw):
    with Session(engine) as session:
        _write_rows(session, "AAPL", interval, df, datetime(2026, 10, 1, 20), **kw)


def test_a_clamped_full_answer_never_shortens_the_cached_daily_bars(engine):
    _write(engine, _bar_frame(date(2021, 10, 4), date(2026, 9, 30)))
    first_before, _, count_before = _span(engine)
    # asked for 5 years (from 2021-10-01), FMP answered with ~3.5 years: a replace used to delete the older bars
    _write(engine, _bar_frame(date(2023, 4, 3), date(2026, 9, 30)), replace=True, requested_from=date(2021, 10, 1))
    first_after, last_after, count_after = _span(engine)
    assert first_after == first_before and count_after == count_before and last_after == date(2026, 9, 30)
    assert history_clamps.clamped_tickers("bars") == 1


def test_a_restated_clamped_answer_still_replaces_so_two_bases_are_never_spliced(engine):
    _write(engine, _bar_frame(date(2021, 10, 4), date(2026, 9, 30)))
    halved = _bar_frame(date(2023, 4, 3), date(2026, 9, 30), close=lambda d: 50.0)  # a 2:1 split restated the overlap
    _write(engine, halved, replace=True, requested_from=date(2021, 10, 1))
    first, _, count = _span(engine)
    assert first == date(2023, 4, 3) and count == len(halved)
    assert history_clamps.clamped_tickers("bars") == 1  # replaced, but visible


def test_ordinary_trimming_to_the_moved_window_is_not_a_clamp(engine):
    _write(engine, _bar_frame(date(2021, 10, 4), date(2026, 9, 30)))
    # a year later the weekly resync asks from 2022-10-01 and gets exactly that: the old year is trimmed as before
    _write(engine, _bar_frame(date(2022, 10, 3), date(2026, 9, 30)), replace=True, requested_from=date(2022, 10, 1))
    assert _span(engine)[0] == date(2022, 10, 3)
    assert history_clamps.clamped_tickers("bars") == 0


def test_a_caller_that_does_not_opt_in_keeps_the_plain_replace(engine):
    _write(engine, _bar_frame(date(2021, 10, 4), date(2026, 9, 30)))
    _write(engine, _bar_frame(date(2023, 4, 3), date(2026, 9, 30)), replace=True)  # no requested_from (the one-off backfill)
    assert _span(engine)[0] == date(2023, 4, 3)


def test_a_young_listing_is_not_a_clamp(engine):
    _write(engine, _bar_frame(date(2025, 6, 2), date(2026, 9, 30)))
    _write(engine, _bar_frame(date(2025, 6, 2), date(2026, 9, 30)), replace=True, requested_from=date(2021, 10, 1))
    assert history_clamps.clamped_tickers("bars") == 0


def test_legacy_non_fmp_intraday_rows_are_still_replaced(engine):
    start = datetime(2025, 1, 6, 9, 30)
    legacy = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 100.0, "volume": 1},
        index=pd.DatetimeIndex([start + timedelta(days=i) for i in range(60)]),
    )
    _write(engine, legacy, interval=INTRADAY_INTERVAL, source=None)  # NULL provenance = legacy Yahoo-era
    fresh = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 100.0, "volume": 1},
        index=pd.DatetimeIndex([start + timedelta(days=30 + i) for i in range(30)]),
    )
    _write(engine, fresh, interval=INTRADAY_INTERVAL, source="fmp", replace=True, requested_from=date(2025, 1, 1))
    first, _, count = _span(engine, INTRADAY_INTERVAL)
    assert count == 30 and first == (start + timedelta(days=30)).date()
