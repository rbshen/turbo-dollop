import re
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

from core.models import Watchlist, WatchlistTicker
from data.watchlists import list_tickers_across_watchlists

PATTERN = re.compile(r"^W[1-5]$")


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


def test_union_dedupes_a_ticker_present_on_both_matching_lists():
    engine = _fresh_engine()
    _seed_watchlist(engine, "W1", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "W2", ["MSFT", "GOOG"])

    with Session(engine) as session:
        tickers, matched = list_tickers_across_watchlists(session, PATTERN)

    assert tickers == ["AAPL", "MSFT", "GOOG"]  # first-seen order, MSFT not duplicated
    assert matched == ["W1", "W2"]


def test_a_third_matching_list_is_also_included_not_just_the_first_two():
    engine = _fresh_engine()
    _seed_watchlist(engine, "W1", ["AAPL"])
    _seed_watchlist(engine, "W2", ["MSFT"])
    _seed_watchlist(engine, "W3", ["GOOG"])

    with Session(engine) as session:
        tickers, matched = list_tickers_across_watchlists(session, PATTERN)

    assert tickers == ["AAPL", "MSFT", "GOOG"]
    assert matched == ["W1", "W2", "W3"]


def test_a_non_matching_name_is_never_consulted():
    engine = _fresh_engine()
    _seed_watchlist(engine, "W1", ["AAPL"])
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])
    _seed_watchlist(engine, "W6", ["YYYY"])  # out of the 1-5 range -- must not match

    with Session(engine) as session:
        tickers, matched = list_tickers_across_watchlists(session, PATTERN)

    assert tickers == ["AAPL"]
    assert matched == ["W1"]


def test_no_matching_watchlists_returns_empty_tickers_and_empty_matched_names():
    engine = _fresh_engine()

    with Session(engine) as session:
        tickers, matched = list_tickers_across_watchlists(session, PATTERN)

    assert tickers == []
    assert matched == []
