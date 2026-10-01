from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from core.models import SavedScreenerFilter, Watchlist, WatchlistTicker
from data.watchlists import (
    MONITORED_WATCHLIST_PATTERN,
    delete_watchlist,
    is_monitored_watchlist_name,
    list_monitored_tickers,
    list_monitored_watchlists,
)


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_watchlist(engine, name: str, tickers: list[str]) -> None:
    now = datetime.now()
    with Session(engine) as session:
        watchlist = Watchlist(name=name, created_at=now, updated_at=now)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        for t in tickers:
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=t, added_at=now))
        session.commit()


@pytest.mark.parametrize("name", ["E1", "E2", "E5", "E6", "E10", "E99", "E1000", "ETF"])
def test_monitored_names_are_matched(name):
    assert is_monitored_watchlist_name(name)


@pytest.mark.parametrize(
    "name",
    ["E0", "E01", "E", "e1", "etf", "Etf", "ETFs", "ETF2", "EE1", "E-1", "E1 ", " E1", "E1.5", "W1", "W5", "W6", "W score passed", "N scores passed", "", "Watchlist"],
)
def test_other_names_are_not_matched(name):
    assert not is_monitored_watchlist_name(name)


def test_the_pattern_has_no_upper_limit_on_the_number():
    assert MONITORED_WATCHLIST_PATTERN.fullmatch("E123456")


def test_union_dedupes_a_ticker_present_on_both_matching_lists():
    engine = _fresh_engine()
    _seed_watchlist(engine, "E1", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "E2", ["MSFT", "GOOG"])

    with Session(engine) as session:
        tickers, matched = list_monitored_tickers(session)

    assert tickers == ["AAPL", "MSFT", "GOOG"]  # first-seen order, MSFT not duplicated
    assert matched == ["E1", "E2"]


def test_numbered_lists_beyond_five_and_the_etf_list_are_included_in_natural_order():
    engine = _fresh_engine()
    _seed_watchlist(engine, "ETF", ["SPY"])
    _seed_watchlist(engine, "E10", ["GOOG"])
    _seed_watchlist(engine, "E2", ["MSFT"])
    _seed_watchlist(engine, "E1", ["AAPL"])

    with Session(engine) as session:
        tickers, matched = list_monitored_tickers(session)
        listed = [w.name for w in list_monitored_watchlists(session)]

    assert matched == listed == ["E1", "E2", "E10", "ETF"]  # E10 after E2, not after E1
    assert tickers == ["AAPL", "MSFT", "GOOG", "SPY"]


def test_a_ticker_on_the_etf_list_and_a_numbered_list_is_only_returned_once():
    engine = _fresh_engine()
    _seed_watchlist(engine, "E1", ["SPY", "AAPL"])
    _seed_watchlist(engine, "ETF", ["SPY", "QQQ"])

    with Session(engine) as session:
        tickers, _ = list_monitored_tickers(session)

    assert tickers == ["SPY", "AAPL", "QQQ"]


def test_a_non_matching_name_is_never_consulted():
    engine = _fresh_engine()
    _seed_watchlist(engine, "E1", ["AAPL"])
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])
    _seed_watchlist(engine, "W1", ["YYYY"])  # the retired name -- must not match
    _seed_watchlist(engine, "E0", ["XXXX"])

    with Session(engine) as session:
        tickers, matched = list_monitored_tickers(session)

    assert tickers == ["AAPL"]
    assert matched == ["E1"]


def test_no_matching_watchlists_returns_empty_tickers_and_empty_matched_names():
    engine = _fresh_engine()

    with Session(engine) as session:
        tickers, matched = list_monitored_tickers(session)

    assert tickers == []
    assert matched == []


def test_no_job_module_keeps_its_own_copy_of_the_watchlist_pattern():
    backend = Path(__file__).resolve().parent.parent
    for rel in (
        "pipeline/nightly_liquidity_zone_calculation.py",
        "pipeline/nightly_entry_signal_calculation.py",
        "pipeline/nightly_warren_signal_calculation.py",
        "pipeline/backfills/backfill_fmp_daily_bars.py",
    ):
        source = (backend / rel).read_text()
        assert "list_monitored_tickers" in source, rel
        assert "WATCHLIST_NAME_PATTERN" not in source, rel
        assert "W[1-5]" not in source, rel


def test_delete_watchlist_also_deletes_saved_screener_filters_that_reference_it():
    engine = _fresh_engine()
    _seed_watchlist(engine, "E1", ["AAPL"])
    now = datetime.now()
    with Session(engine) as session:
        watchlist_id = session.exec(select(Watchlist).where(Watchlist.name == "E1")).one().id
        session.add(
            SavedScreenerFilter(
                name="Scoped view",
                universe="all",
                sort_field="overall_score",
                sort_direction="desc",
                filters_json="{}",
                watchlist_id=watchlist_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            SavedScreenerFilter(
                name="Unscoped view",
                universe="sp500",
                sort_field="overall_score",
                sort_direction="desc",
                filters_json="{}",
                watchlist_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    with Session(engine) as session:
        assert delete_watchlist(session, watchlist_id) is True

    with Session(engine) as session:
        remaining = session.exec(select(SavedScreenerFilter)).all()

    assert [f.name for f in remaining] == ["Unscoped view"]
