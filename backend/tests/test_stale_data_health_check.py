import json
from datetime import date, datetime, timedelta

import httpx
from sqlmodel import Session, SQLModel, create_engine

import pipeline.nightly_fundamentals_fetch as nightly
import pipeline.stale_data_health_check as health_check
from core.models import FundamentalsCache, IndexConstituent, TickerScore, Watchlist, WatchlistTicker


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(health_check, "engine", engine)
    monkeypatch.setattr(nightly, "engine", engine)
    monkeypatch.setattr(health_check, "LOG_PATH", tmp_path / "test_stale.log")
    # Safety net: sync_delisted_flags makes live FMP calls (paged /delisted-companies) -- the
    # default fake serves an empty list, so no test reaches the network by accident.
    _patch_delisted(monkeypatch, [])
    return engine


def _patch_delisted(monkeypatch, rows: list[dict], *, page_size: int = 100, fail_from_page: int | None = None):
    """Serve `rows` as FMP's paged /delisted-companies. Returns the list of pages requested."""
    pages: list[int] = []

    async def fake(page, limit=100):
        pages.append(page)
        if fail_from_page is not None and page >= fail_from_page:
            raise httpx.ConnectError("boom")
        return rows[page * page_size : (page + 1) * page_size]

    monkeypatch.setattr(health_check.fmp_client, "get_delisted_companies", fake)
    return pages


def _listed(symbol: str, delisted: str, ipo: str = "1990-01-01", exchange: str = "NYSE") -> dict:
    return {"symbol": symbol, "companyName": symbol, "exchange": exchange, "ipoDate": ipo, "delistedDate": delisted}


def _seed_profile(session, ticker, days_old, ipo_date: str | None = None):
    session.add(
        FundamentalsCache(
            ticker=ticker,
            statement_type="profile",
            period="annual" if ipo_date is None else "latest",
            fetched_at=datetime.now() - timedelta(days=days_old),
            raw_json="[]" if ipo_date is None else json.dumps([{"symbol": ticker, "ipoDate": ipo_date}]),
        )
    )


def test_fresh_stale_and_never_fetched_are_classified_correctly(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "FRESHCO", days_old=1)
        _seed_profile(session, "STALECO", days_old=20)
        session.commit()

    result = health_check.check_staleness(["FRESHCO", "STALECO", "NEVERCO"], threshold_days=10)

    assert result["fresh"] == ["FRESHCO"]
    assert result["stale"] == [("STALECO", 20)]
    assert result["never_fetched"] == ["NEVERCO"]


def test_threshold_boundary_is_exclusive_of_the_threshold_itself(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "EXACTLYCO", days_old=10)
        session.commit()

    result = health_check.check_staleness(["EXACTLYCO"], threshold_days=10)

    assert result["fresh"] == ["EXACTLYCO"]  # days_old == threshold is not > threshold


def test_report_formatting_lists_stale_and_never_fetched_tickers():
    result = {"fresh": ["A"], "stale": [("B", 15), ("C", 30)], "never_fetched": ["D"]}

    report = health_check._format_report(result, total=4, threshold_days=10)

    assert "Fresh:         1" in report
    assert "Stale:         2" in report
    assert "Never fetched: 1" in report
    assert "C: 30d" in report and "B: 15d" in report
    assert "D" in report


def test_main_uses_the_universe_ticker_list_and_writes_a_report(monkeypatch, tmp_path, capsys):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        _seed_profile(session, "AAPL", days_old=1)
        session.commit()

    result = health_check.main(threshold_days=10)

    assert result["fresh"] == ["AAPL"]
    captured = capsys.readouterr()
    assert "Stale-data health check (1 tickers" in captured.out


def test_main_uses_the_full_tracked_universe_not_just_index_constituents(monkeypatch, tmp_path):
    # Regression test for the 2026-09-11 widening (cron audit finding #6/B):
    # a watchlisted-only ticker (never an index member, never cached, never
    # scored) whose nightly refresh silently broke used to be invisible to
    # this report, because it only checked load_universe_tickers (S&P 500 +
    # Dow). It must now show up via load_full_tracked_universe, the same
    # helper nightly_fundamentals_fetch.py actually keeps fresh against.
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        _seed_profile(session, "AAPL", days_old=1)

        # IREN: cached FMP data only, never an index member.
        _seed_profile(session, "IREN", days_old=20)

        # SEZL: has a TickerScore row only, no cache, no index membership.
        session.add(TickerScore(ticker="SEZL", overall_score=66, overall_verdict="Fail", computed_at=datetime.now()))

        # ASML: watchlisted only -- not indexed, not cached, not scored.
        watchlist = Watchlist(name="Main", created_at=datetime.now(), updated_at=datetime.now())
        session.add(watchlist)
        session.commit()
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="ASML", added_at=datetime.now()))
        session.commit()

    result = health_check.main(threshold_days=10)

    assert result["fresh"] == ["AAPL"]
    assert result["stale"] == [("IREN", 20)]
    assert result["never_fetched"] == ["ASML", "SEZL"]


# --- Delisted-ticker flagging (FMP /delisted-companies) ---


def _seed_scores(engine, *tickers):
    with Session(engine) as session:
        for t in tickers:
            session.add(TickerScore(ticker=t, overall_score=50, computed_at=datetime.now()))
        session.commit()


def _delisted_at(engine, ticker):
    with Session(engine) as session:
        return session.get(TickerScore, ticker).delisted_at


def test_flags_a_tracked_ticker_listed_as_delisted(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "TWTR", "AAPL")
    _patch_delisted(monkeypatch, [_listed("TWTR", "2022-10-27"), _listed("ZZZZ", "2020-01-01")])

    result = health_check.sync_delisted_flags(["TWTR", "AAPL"])

    assert result == {"newly_flagged": ["TWTR"], "skipped": False, "complete": True}
    assert _delisted_at(engine, "TWTR") is not None and _delisted_at(engine, "AAPL") is None


def test_pages_until_an_empty_page(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "LATE")
    rows = [_listed(f"X{i}", "2020-01-01") for i in range(250)] + [_listed("LATE", "2021-01-01")]
    pages = _patch_delisted(monkeypatch, rows)

    assert health_check.sync_delisted_flags(["LATE"])["newly_flagged"] == ["LATE"]
    assert pages == [0, 1, 2, 3]  # 251 rows -> 3 populated pages, the 4th (empty) ends it


def test_absence_from_the_list_is_never_evidence(monkeypatch, tmp_path):
    """No flag for an unlisted ticker however stale its bars are, and an existing flag is
    never cleared by absence (no staleness heuristic, no revival)."""
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerScore(ticker="OLDFLAG", overall_score=50, computed_at=datetime.now(), delisted_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="QUIET", overall_score=50, computed_at=datetime.now()))
        session.commit()

    result = health_check.sync_delisted_flags(["OLDFLAG", "QUIET"])

    assert result["newly_flagged"] == []
    assert _delisted_at(engine, "OLDFLAG") == datetime(2026, 1, 1) and _delisted_at(engine, "QUIET") is None


def test_a_future_delisted_date_is_a_scheduled_delisting_not_a_delisting(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "SOON")
    future = (date.today() + timedelta(days=30)).isoformat()
    _patch_delisted(monkeypatch, [_listed("SOON", future)])

    assert health_check.sync_delisted_flags(["SOON"])["newly_flagged"] == []


def test_a_reused_symbol_whose_profile_ipo_is_after_the_delisting_is_not_flagged(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "REUSED", "REAL")
    with Session(engine) as session:
        _seed_profile(session, "REUSED", days_old=1, ipo_date="2024-05-01")  # a newer company
        _seed_profile(session, "REAL", days_old=1, ipo_date="1994-03-11")
        session.commit()
    _patch_delisted(monkeypatch, [_listed("REUSED", "2019-06-01"), _listed("REAL", "2026-08-17")])

    assert health_check.sync_delisted_flags(["REUSED", "REAL"])["newly_flagged"] == ["REAL"]


def test_several_rows_for_one_symbol_flag_it_once_when_any_qualifies(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "DUP")
    with Session(engine) as session:
        _seed_profile(session, "DUP", days_old=1, ipo_date="2015-01-01")
        session.commit()
    _patch_delisted(monkeypatch, [_listed("DUP", "2010-01-01"), _listed("DUP", "2024-01-01")])

    assert health_check.sync_delisted_flags(["DUP"])["newly_flagged"] == ["DUP"]


def test_a_class_share_symbol_from_fmp_matches_the_hyphen_form(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "BF-B")
    _patch_delisted(monkeypatch, [_listed("BF.B", "2026-01-05")])

    assert health_check.sync_delisted_flags(["BF-B"])["newly_flagged"] == ["BF-B"]


def test_an_already_flagged_ticker_is_not_re_flagged_or_touched(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    original = datetime(2026, 9, 24, 10, 17)
    with Session(engine) as session:
        session.add(TickerScore(ticker="TWTR", overall_score=50, computed_at=datetime.now(), delisted_at=original))
        session.commit()
    _patch_delisted(monkeypatch, [_listed("TWTR", "2022-10-27")])

    assert health_check.sync_delisted_flags(["TWTR"])["newly_flagged"] == []
    assert _delisted_at(engine, "TWTR") == original


def test_a_page_error_uses_what_was_fetched_and_reports_incomplete(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "EARLY", "UNSEEN")
    rows = [_listed(f"X{i}", "2020-01-01") for i in range(99)] + [_listed("EARLY", "2021-01-01")] + [_listed("UNSEEN", "2021-01-01")]
    _patch_delisted(monkeypatch, rows, fail_from_page=1)

    result = health_check.sync_delisted_flags(["EARLY", "UNSEEN"])

    assert result == {"newly_flagged": ["EARLY"], "skipped": False, "complete": False}


def test_skipped_without_any_fetch_while_corporate_events_is_off(monkeypatch, tmp_path):
    import core.data_groups as dg

    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_scores(engine, "TWTR")
    pages = _patch_delisted(monkeypatch, [_listed("TWTR", "2022-10-27")])
    dg.set_group_enabled("corporate_events", False)

    result = health_check.sync_delisted_flags(["TWTR"])

    assert result["skipped"] is True and pages == [] and _delisted_at(engine, "TWTR") is None


def test_sync_delisted_flags_never_touches_other_ticker_score_fields(monkeypatch, tmp_path):
    # History (this row's other fields, and by extension FundamentalsCache/Screener/Watchlist/
    # ticker-page data derived from it) must stay fully intact for a flagged ticker.
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerScore(ticker="TWTR", company_name="Twitter Inc", overall_score=75, overall_verdict="Pass", computed_at=datetime.now()))
        session.commit()
    _patch_delisted(monkeypatch, [_listed("TWTR", "2022-10-27")])

    health_check.sync_delisted_flags(["TWTR"])

    with Session(engine) as session:
        row = session.get(TickerScore, "TWTR")
    assert (row.company_name, row.overall_score, row.overall_verdict) == ("Twitter Inc", 75, "Pass")


def test_sync_delisted_flags_empty_ticker_list(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    assert health_check.sync_delisted_flags([]) == {"newly_flagged": [], "skipped": False, "complete": True}


def test_load_delisted_tickers_returns_only_flagged(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerScore(ticker="FLAGGED", overall_score=50, computed_at=datetime.now(), delisted_at=datetime.now()))
        session.add(TickerScore(ticker="CLEAN", overall_score=90, computed_at=datetime.now()))
        session.commit()
        result = health_check.load_delisted_tickers(session)

    assert result == {"FLAGGED"}


def test_main_integrates_delisted_flagging_into_its_result_and_report(monkeypatch, tmp_path, capsys):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="TWTR", company_name="Twitter", last_synced_at=datetime.now()))
        session.add(TickerScore(ticker="TWTR", overall_score=50, computed_at=datetime.now()))
        _seed_profile(session, "TWTR", days_old=1)
        session.commit()
    _patch_delisted(monkeypatch, [_listed("TWTR", "2022-10-27")])

    result = health_check.main(threshold_days=10)

    assert result["delisted"] == {"newly_flagged": ["TWTR"], "skipped": False, "complete": True}
    assert "Newly flagged delisted: TWTR" in capsys.readouterr().out
