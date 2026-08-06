from datetime import datetime

from sqlmodel import Session, select

from core.models import Watchlist, WatchlistTicker


def list_watchlists(session: Session) -> list[Watchlist]:
    return list(session.exec(select(Watchlist).order_by(Watchlist.name)).all())


def get_watchlist_by_name(session: Session, name: str) -> Watchlist | None:
    return session.exec(select(Watchlist).where(Watchlist.name == name)).first()


def list_watchlist_tickers(session: Session, watchlist_id: int) -> list[WatchlistTicker]:
    return list(
        session.exec(
            select(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist_id).order_by(WatchlistTicker.added_at)
        ).all()
    )


def create_watchlist(session: Session, name: str) -> Watchlist:
    now = datetime.now()
    row = Watchlist(name=name, created_at=now, updated_at=now)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_watchlist(
    session: Session,
    watchlist_id: int,
    *,
    name: str | None = None,
    sort_field: str | None = None,
    sort_direction: str | None = None,
) -> Watchlist | None:
    row = session.get(Watchlist, watchlist_id)
    if row is None:
        return None
    if name is not None:
        row.name = name
    if sort_field is not None:
        row.sort_field = sort_field
    if sort_direction is not None:
        row.sort_direction = sort_direction
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_watchlist(session: Session, watchlist_id: int) -> bool:
    row = session.get(Watchlist, watchlist_id)
    if row is None:
        return False
    # No SQLite ON DELETE CASCADE (see WatchlistTicker's docstring) -- delete
    # child rows explicitly before the parent.
    for ticker_row in list_watchlist_tickers(session, watchlist_id):
        session.delete(ticker_row)
    session.delete(row)
    session.commit()
    return True


def count_net_new_tickers(session: Session, watchlist_id: int, tickers: list[str]) -> tuple[int, int]:
    """Returns (existing_count, net_new_count) -- net_new_count is how many
    of `tickers` aren't already members (deduped against both current
    membership and each other), which is what actually counts against a
    watchlist's 100-ticker capacity. Shared by the single-add and bulk-add
    endpoints so re-adding an already-present ticker never counts against
    the cap, regardless of entry point."""
    existing = {t.ticker for t in list_watchlist_tickers(session, watchlist_id)}
    net_new = {t for t in tickers if t not in existing}
    return len(existing), len(net_new)


def add_watchlist_ticker(session: Session, watchlist_id: int, ticker: str) -> WatchlistTicker:
    row = WatchlistTicker(watchlist_id=watchlist_id, ticker=ticker, added_at=datetime.now())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def bulk_add_watchlist_tickers(session: Session, watchlist_id: int, tickers: list[str]) -> tuple[int, int]:
    """Adds every ticker not already a member, in one session/commit.
    Returns (added, already_present) so the caller can report e.g. "Added 47
    (3 already in this watchlist)" rather than erroring on the overlap --
    same dedupe the single-add endpoint already relies on via the unique
    constraint, just checked up front instead of racing the DB for it.
    Also naturally dedupes a caller-supplied list with repeats."""
    existing = {t.ticker for t in list_watchlist_tickers(session, watchlist_id)}
    now = datetime.now()
    added = 0
    already_present = 0
    for ticker in tickers:
        if ticker in existing:
            already_present += 1
            continue
        session.add(WatchlistTicker(watchlist_id=watchlist_id, ticker=ticker, added_at=now))
        existing.add(ticker)
        added += 1
    session.commit()
    return added, already_present


def get_watchlist_ticker(session: Session, watchlist_id: int, ticker: str) -> WatchlistTicker | None:
    return session.exec(
        select(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist_id, WatchlistTicker.ticker == ticker)
    ).first()


def remove_watchlist_ticker(session: Session, watchlist_id: int, ticker: str) -> bool:
    row = get_watchlist_ticker(session, watchlist_id, ticker)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
