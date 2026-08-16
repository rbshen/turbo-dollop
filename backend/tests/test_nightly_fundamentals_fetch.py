import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

import pipeline.nightly_fundamentals_fetch as nightly
from core.models import FundamentalsCache, IndexConstituent, TickerScore, Watchlist, WatchlistTicker


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly, "engine", engine)
    # main() calls configure_logging(LOG_PATH) with force=True, which
    # reconfigures the ROOT logger for the rest of this pytest process --
    # pointing it at a tmp_path file instead of the real production log
    # keeps test runs from polluting backend/logs/nightly_fundamentals_fetch.log.
    monkeypatch.setattr(nightly, "LOG_PATH", tmp_path / "test_nightly.log")
    return engine


def _patch_all_steps(monkeypatch, calls, fail_for: set[str] | None = None):
    fail_for = fail_for or set()

    def make_step(name):
        async def fn(ticker, **kwargs):
            calls.append((ticker, name))
            if ticker in fail_for:
                raise RuntimeError(f"simulated failure fetching {name} for {ticker}")
            return None

        return fn

    async def fake_compute_ticker_score(ticker, cache_only=False):
        calls.append((ticker, "ticker_score", cache_only))
        return None

    monkeypatch.setattr(nightly, "get_step1_data", make_step("step1"))
    monkeypatch.setattr(nightly, "get_step2_data", make_step("step2"))
    monkeypatch.setattr(nightly, "get_step4_data", make_step("step4"))
    monkeypatch.setattr(nightly, "get_step5_data", make_step("step5"))
    monkeypatch.setattr(nightly, "get_segmentation_data", make_step("segmentation"))
    monkeypatch.setattr(nightly, "get_summary", make_step("summary"))
    monkeypatch.setattr(nightly, "compute_ticker_score", fake_compute_ticker_score)


def test_load_sp500_tickers_reads_from_the_index_constituent_table(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="sp500", ticker="MSFT", company_name="Microsoft", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="other-index", ticker="XYZ", company_name="Not S&P", last_synced_at=datetime.now()))
        session.commit()

        tickers = nightly.load_sp500_tickers(session)

    assert set(tickers) == {"AAPL", "MSFT"}


def test_load_universe_tickers_unions_sp500_and_dow_without_duplicates(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        # AMGN is in both lists today -- must appear once, not twice.
        session.add(IndexConstituent(index_name="sp500", ticker="AMGN", company_name="Amgen", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="dow", ticker="AMGN", company_name="Amgen", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="dow", ticker="MMM", company_name="3M", last_synced_at=datetime.now()))
        session.commit()

        tickers = nightly.load_universe_tickers(session)

    assert sorted(tickers) == ["AAPL", "AMGN", "MMM"]


def test_load_full_tracked_universe_unions_index_score_cache_and_watchlist_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        # AAPL: index member only.
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        # IREN: cached FMP data but never an index member and no TickerScore row.
        session.add(FundamentalsCache(ticker="IREN", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        # SEZL: has a TickerScore row but no cache rows.
        session.add(TickerScore(ticker="SEZL", overall_score=66, overall_verdict="Fail", computed_at=datetime.now()))
        # MSFT: appears in two of the sources above -- must not be double-counted.
        session.add(IndexConstituent(index_name="sp500", ticker="MSFT", company_name="Microsoft", last_synced_at=datetime.now()))
        session.add(FundamentalsCache(ticker="MSFT", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        session.commit()

        # ASML: watchlisted only -- not indexed, not cached, not scored. This is
        # the exact 2026-08-06 "watchlisted" gap this function exists to close.
        watchlist = Watchlist(name="Semis", created_at=datetime.now(), updated_at=datetime.now())
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="ASML", added_at=datetime.now()))
        session.commit()

    with Session(engine) as session:
        tickers = nightly.load_full_tracked_universe(session)

    assert tickers == ["AAPL", "ASML", "IREN", "MSFT", "SEZL"]


def test_load_full_tracked_universe_excludes_non_profile_cache_rows(monkeypatch, tmp_path):
    # FundamentalsCache also stores non-ticker lookups under a ticker-shaped key --
    # confirmed live via Valuation's FX spot-rate cache (statement_type="forex_rate",
    # ticker="EURUSD"). A currency pair must never enter the universe this job runs
    # the full live-fetch pipeline against.
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        session.add(FundamentalsCache(ticker="EURUSD", statement_type="forex_rate", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        session.commit()

    with Session(engine) as session:
        tickers = nightly.load_full_tracked_universe(session)

    assert tickers == ["AAPL"]


def test_a_failing_ticker_does_not_abort_the_run(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, str]] = []
    _patch_all_steps(monkeypatch, calls, fail_for={"BADCO"})
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    summary = asyncio.run(nightly.main(tickers=["AAPL", "BADCO", "MSFT"]))

    # Every ticker was attempted, including the ones after the failure --
    # a single bad ticker must not stop the rest of the run.
    assert {c[0] for c in calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["processed"] == 3
    assert summary["failed"] == 1
    assert summary["failures"] == [("BADCO", "simulated failure fetching step1 for BADCO")]


def test_summary_reports_all_expected_fields(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, str]] = []
    _patch_all_steps(monkeypatch, calls)
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    summary = asyncio.run(nightly.main(tickers=["AAPL"]))

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["failures"] == []
    assert "calls_made" in summary
    assert "duration_seconds" in summary
    # All six existing get_*_data/get_summary functions must be called for
    # every ticker -- nothing bespoke, reusing the actual pipeline -- plus
    # the Screener score computation that now runs after them.
    assert {c[1] for c in calls} == {"step1", "step2", "step4", "step5", "segmentation", "summary", "ticker_score"}


def test_ticker_score_is_computed_cache_only_after_each_tickers_fetch(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple] = []
    _patch_all_steps(monkeypatch, calls)
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    asyncio.run(nightly.main(tickers=["AAPL", "MSFT"]))

    score_calls = [c for c in calls if c[1] == "ticker_score"]
    assert {c[0] for c in score_calls} == {"AAPL", "MSFT"}
    # cache_only=True -- the raw data was just fetched/cached moments
    # earlier in this same run, so recomputing scores must add zero extra
    # FMP calls.
    assert all(c[2] is True for c in score_calls)


def test_refresh_one_ticker_calls_get_summary_with_live_quote_false(monkeypatch, tmp_path):
    # 2026-08-16 cron thundering-herd follow-up: the nightly job must not
    # force-fetch quote live for the whole tracked universe every night --
    # see get_summary's own docstring for why. A regression back to the
    # default (live_quote=True, or omitting the kwarg entirely) would
    # silently reintroduce that.
    _fresh_engine(monkeypatch, tmp_path)
    live_quote_seen = {}

    async def fake_get_summary(ticker, live_quote=True):
        live_quote_seen[ticker] = live_quote
        return None

    async def noop(ticker, **kwargs):
        return None

    async def fake_compute_ticker_score(ticker, cache_only=False):
        return None

    monkeypatch.setattr(nightly, "get_step1_data", noop)
    monkeypatch.setattr(nightly, "get_step2_data", noop)
    monkeypatch.setattr(nightly, "get_step4_data", noop)
    monkeypatch.setattr(nightly, "get_step5_data", noop)
    monkeypatch.setattr(nightly, "get_segmentation_data", noop)
    monkeypatch.setattr(nightly, "get_summary", fake_get_summary)
    monkeypatch.setattr(nightly, "compute_ticker_score", fake_compute_ticker_score)
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    asyncio.run(nightly.main(tickers=["AAPL"]))

    assert live_quote_seen == {"AAPL": False}


def test_refresh_one_ticker_calls_get_step5_data_with_sec_cross_check_disabled(monkeypatch, tmp_path):
    # 2026-08-16 SEC EDGAR nightly-sweep fix: the bulk sweep must never let
    # get_step5_data's on-demand SEC cross-check fire (SEC's rate-limit
    # penalty for exceeding 10 req/sec is a 10-minute lockout). A regression
    # back to the default (allow_sec_cross_check=True, or omitting the
    # kwarg entirely) would silently reintroduce that.
    _fresh_engine(monkeypatch, tmp_path)
    step5_kwargs_seen = {}

    async def fake_get_step5_data(ticker, **kwargs):
        step5_kwargs_seen[ticker] = kwargs
        return None

    async def noop(ticker, **kwargs):
        return None

    async def fake_compute_ticker_score(ticker, cache_only=False):
        return None

    monkeypatch.setattr(nightly, "get_step1_data", noop)
    monkeypatch.setattr(nightly, "get_step2_data", noop)
    monkeypatch.setattr(nightly, "get_step4_data", noop)
    monkeypatch.setattr(nightly, "get_step5_data", fake_get_step5_data)
    monkeypatch.setattr(nightly, "get_segmentation_data", noop)
    monkeypatch.setattr(nightly, "get_summary", noop)
    monkeypatch.setattr(nightly, "compute_ticker_score", fake_compute_ticker_score)
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    asyncio.run(nightly.main(tickers=["AAPL"]))

    assert step5_kwargs_seen == {"AAPL": {"allow_sec_cross_check": False}}


def test_pacing_is_configured_before_the_run_starts(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, str]] = []
    _patch_all_steps(monkeypatch, calls)
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    asyncio.run(nightly.main(tickers=["AAPL"]))

    expected_interval = 60.0 / nightly.TARGET_REQUESTS_PER_MINUTE
    assert nightly.fmp_client.min_request_interval == expected_interval


def test_empty_ticker_list_is_handled_without_crashing(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(nightly.main(tickers=[]))

    assert summary == {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": []}


def test_fmp_disabled_skips_the_run_before_any_fetch_or_universe_lookup(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(nightly.settings, "fmp_enabled", False)

    calls: list[tuple[str, str]] = []
    _patch_all_steps(monkeypatch, calls)

    def fail_if_queried(*args, **kwargs):
        raise AssertionError("must not resolve the ticker universe while FMP is paused")

    monkeypatch.setattr(nightly, "load_full_tracked_universe", fail_if_queried)

    summary = asyncio.run(nightly.main())  # tickers=None -- would normally resolve the full universe

    assert summary["processed"] == 0
    assert summary["skipped"] is True
    assert calls == []  # no get_stepN_data/get_summary/compute_ticker_score call was ever made
