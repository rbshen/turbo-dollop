import re
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

from core.models import SavedScreenerFilter, Watchlist, WatchlistTicker
from data.watchlists import delete_watchlist, list_tickers_across_watchlists

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


def test_delete_watchlist_also_deletes_saved_screener_filters_that_reference_it():
    engine = _fresh_engine()
    _seed_watchlist(engine, "W1", ["AAPL"])
    now = datetime.now()
    with Session(engine) as session:
        watchlist_id = session.exec(select(Watchlist).where(Watchlist.name == "W1")).one().id
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
