from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

import clients.shared_bars_cache as shared_bars_cache
import pipeline.nightly_fundamentals_fetch as nightly
import pipeline.stale_data_health_check as health_check
from core.models import FundamentalsCache, IndexConstituent, SharedBarsCache, TickerScore, Watchlist, WatchlistTicker


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(health_check, "engine", engine)
    monkeypatch.setattr(nightly, "engine", engine)
    # sync_delisted_flags reads SharedBarsCache through
    # clients.shared_bars_cache's OWN engine reference (last_bar_ages_days
    # -> _cache_span), not health_check's -- patched here too, same
    # engine-isolation convention CLAUDE.md's "Ad-hoc reproduction scripts"
    # section documents (every module's own `engine` import must be
    # patched, not just the caller's).
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    monkeypatch.setattr(health_check, "LOG_PATH", tmp_path / "test_stale.log")
    return engine


def _seed_daily_bar(session, ticker, days_old):
    session.add(
        SharedBarsCache(
            ticker=ticker,
            interval="1d",
            bar_time=datetime.now() - timedelta(days=days_old),
            open=1.0, high=1.0, low=1.0, close=1.0, volume=100,
            fetched_at=datetime.now(),
        )
    )


def _seed_profile(session, ticker, days_old):
    session.add(
        FundamentalsCache(
            ticker=ticker,
            statement_type="profile",
            period="annual",
            fetched_at=datetime.now() - timedelta(days=days_old),
            raw_json="[]",
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


# --- Delisted-ticker flagging (sync_delisted_flags / find_delisted_candidates) ---


def test_flags_a_ticker_stale_on_both_providers(monkeypatch, tmp_path):
    # settings.massive_enabled=True means every SharedBarsCache "1d" row in
    # scope was fetched via clients/daily_bar_sources.py's
    # MassiveWithYahooFallback -- Massive tried first, Yahoo as an
    # automatic per-ticker fallback -- so a last bar this old genuinely
    # reflects BOTH providers failing to produce anything newer.
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    with Session(engine) as session:
        session.add(TickerScore(ticker="TWTR", overall_score=50, computed_at=datetime.now()))
        _seed_daily_bar(session, "TWTR", days_old=45)
        session.commit()

    result = health_check.sync_delisted_flags(["TWTR"])

    assert result == {"newly_flagged": ["TWTR"], "newly_cleared": []}
    with Session(engine) as session:
        row = session.get(TickerScore, "TWTR")
    assert row.delisted_at is not None


def test_does_not_flag_when_only_one_provider_was_checked(monkeypatch, tmp_path):
    # massive_enabled=False -> get_daily_bar_source() returns a plain
    # YahooDailySource (clients/daily_bar_sources.py) -- every cached bar
    # in scope only ever reflects Yahoo's own attempts, single-provider
    # evidence, which must never flag a ticker even though it's just as
    # stale as the dual-provider case above.
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", False)
    with Session(engine) as session:
        session.add(TickerScore(ticker="TWTR", overall_score=50, computed_at=datetime.now()))
        _seed_daily_bar(session, "TWTR", days_old=45)
        session.commit()

    result = health_check.sync_delisted_flags(["TWTR"])

    assert result == {"newly_flagged": [], "newly_cleared": []}
    with Session(engine) as session:
        row = session.get(TickerScore, "TWTR")
    assert row.delisted_at is None


def test_does_not_flag_a_ticker_only_mildly_stale(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL", overall_score=90, computed_at=datetime.now()))
        _seed_daily_bar(session, "AAPL", days_old=5)
        session.commit()

    result = health_check.sync_delisted_flags(["AAPL"])

    assert result == {"newly_flagged": [], "newly_cleared": []}


def test_threshold_boundary_is_exclusive_for_delisted_flagging(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    with Session(engine) as session:
        session.add(TickerScore(ticker="EXACT", overall_score=50, computed_at=datetime.now()))
        _seed_daily_bar(session, "EXACT", days_old=30)
        session.commit()

    result = health_check.sync_delisted_flags(["EXACT"], threshold_days=30)

    assert result == {"newly_flagged": [], "newly_cleared": []}  # 30 == threshold is not > threshold


def test_never_flagged_ticker_with_no_cached_bars_at_all(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    with Session(engine) as session:
        session.add(TickerScore(ticker="NEVERFETCHED", overall_score=50, computed_at=datetime.now()))
        session.commit()

    result = health_check.sync_delisted_flags(["NEVERFETCHED"])

    assert result == {"newly_flagged": [], "newly_cleared": []}


def test_non_us_ticker_never_flagged_even_when_very_stale(monkeypatch, tmp_path):
    # Massive is US-market-only (core.tickers.is_non_us_ticker) -- a non-US
    # ticker's daily bars come from Yahoo alone by design
    # (route_by_source), so its own staleness is single-provider evidence
    # only and must never flag it, regardless of massive_enabled.
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    with Session(engine) as session:
        session.add(TickerScore(ticker="0700.HK", overall_score=50, computed_at=datetime.now()))
        _seed_daily_bar(session, "0700.HK", days_old=90)
        session.commit()

    result = health_check.sync_delisted_flags(["0700.HK"])

    assert result == {"newly_flagged": [], "newly_cleared": []}


def test_already_flagged_ticker_is_not_re_flagged_or_touched(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    original_flagged_at = datetime.now() - timedelta(days=10)
    with Session(engine) as session:
        session.add(TickerScore(ticker="TWTR", overall_score=50, computed_at=datetime.now(), delisted_at=original_flagged_at))
        _seed_daily_bar(session, "TWTR", days_old=45)
        session.commit()

    result = health_check.sync_delisted_flags(["TWTR"])

    assert result == {"newly_flagged": [], "newly_cleared": []}
    with Session(engine) as session:
        row = session.get(TickerScore, "TWTR")
    assert row.delisted_at == original_flagged_at


def test_auto_clears_when_a_fresh_bar_reappears(monkeypatch, tmp_path):
    # Symbol reuse/relisting under the same ticker (cf. the earlier PARA
    # case) -- a fresh bar disproves "still delisted" regardless of
    # massive_enabled, since even a single provider serving a real recent
    # bar is conclusive.
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", False)
    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="PARA", overall_score=50, computed_at=datetime.now(), delisted_at=datetime.now() - timedelta(days=5)
            )
        )
        _seed_daily_bar(session, "PARA", days_old=1)
        session.commit()

    result = health_check.sync_delisted_flags(["PARA"])

    assert result == {"newly_flagged": [], "newly_cleared": ["PARA"]}
    with Session(engine) as session:
        row = session.get(TickerScore, "PARA")
    assert row.delisted_at is None


def test_sync_delisted_flags_never_touches_other_ticker_score_fields(monkeypatch, tmp_path):
    # History (this row's other fields, and by extension FundamentalsCache/
    # Screener/Watchlist/ticker-page data derived from it) must stay fully
    # intact for a flagged ticker -- only delisted_at itself changes.
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="TWTR", company_name="Twitter Inc", overall_score=75, overall_verdict="Pass", computed_at=datetime.now()
            )
        )
        _seed_daily_bar(session, "TWTR", days_old=45)
        session.commit()

    health_check.sync_delisted_flags(["TWTR"])

    with Session(engine) as session:
        row = session.get(TickerScore, "TWTR")
    assert row.company_name == "Twitter Inc"
    assert row.overall_score == 75
    assert row.overall_verdict == "Pass"


def test_sync_delisted_flags_empty_ticker_list(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    assert health_check.sync_delisted_flags([]) == {"newly_flagged": [], "newly_cleared": []}


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
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="TWTR", company_name="Twitter", last_synced_at=datetime.now()))
        session.add(TickerScore(ticker="TWTR", overall_score=50, computed_at=datetime.now()))
        _seed_profile(session, "TWTR", days_old=1)
        _seed_daily_bar(session, "TWTR", days_old=45)
        session.commit()

    result = health_check.main(threshold_days=10)

    assert result["delisted"] == {"newly_flagged": ["TWTR"], "newly_cleared": []}
    captured = capsys.readouterr()
    assert "Newly flagged delisted: TWTR" in captured.out
