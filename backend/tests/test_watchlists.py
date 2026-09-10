from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

from core.models import Watchlist, WatchlistTicker
from data.watchlists import list_tickers_across_watchlists


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


def test_union_dedupes_a_ticker_present_on_both_lists():
    engine = _fresh_engine()
    _seed_watchlist(engine, "W1", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "W2", ["MSFT", "GOOG"])

    with Session(engine) as session:
        tickers, missing = list_tickers_across_watchlists(session, ["W1", "W2"])

    assert tickers == ["AAPL", "MSFT", "GOOG"]  # first-seen order, MSFT not duplicated
    assert missing == []


def test_a_third_unrelated_list_is_never_consulted():
    engine = _fresh_engine()
    _seed_watchlist(engine, "W1", ["AAPL"])
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])

    with Session(engine) as session:
        tickers, missing = list_tickers_across_watchlists(session, ["W1", "W2"])

    assert tickers == ["AAPL"]
    assert missing == ["W2"]


def test_a_missing_list_is_reported_but_does_not_error():
    engine = _fresh_engine()
    _seed_watchlist(engine, "W1", ["AAPL"])

    with Session(engine) as session:
        tickers, missing = list_tickers_across_watchlists(session, ["W1", "W2"])

    assert tickers == ["AAPL"]
    assert missing == ["W2"]


def test_both_lists_missing_returns_empty_tickers_and_both_names_missing():
    engine = _fresh_engine()

    with Session(engine) as session:
        tickers, missing = list_tickers_across_watchlists(session, ["W1", "W2"])

    assert tickers == []
    assert missing == ["W1", "W2"]
