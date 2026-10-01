import re
from datetime import datetime

from sqlmodel import Session, select

from core.models import SavedScreenerFilter, Watchlist, WatchlistTicker
from core.tickers import normalize_ticker


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


# The one definition of which watchlists the nightly technical jobs (Liquidity Zones,
# BB+RSI, Warren) read, and which on-demand "not tracked" text refers to. A watchlist is
# "monitored" when its name is E<positive integer> (E1, E6, E10, ... -- no upper limit) or
# exactly "ETF". Case-sensitive full match, no leading zeros: E0, E01, e1, ETFs, W1 and
# "W score passed" are all NOT monitored. Replaced the ^W[1-5]$ pattern that was copied
# into each nightly job (see docs/specs/liquidity-zones.md, CLAUDE.md "Watchlists").
MONITORED_WATCHLIST_PATTERN = re.compile(r"E[1-9][0-9]*|ETF")

# The list the ETF page's "Add to watchlist" button adds to (created on first use). It is itself a
# monitored list -- is_monitored_watchlist_name(ETF_WATCHLIST_NAME) is pinned by tests.
ETF_WATCHLIST_NAME = "ETF"

_NATURAL_SORT_DIGITS = re.compile(r"(\d+)")


def is_monitored_watchlist_name(name: str) -> bool:
    return MONITORED_WATCHLIST_PATTERN.fullmatch(name) is not None


def _natural_name_key(name: str) -> list[tuple[int, int | str]]:
    """E1, E2, ..., E10, ETF -- digits compare numerically ("E10" after "E9", not after
    "E1"). Each part is tagged so an int is never compared against a str."""
    return [(0, int(part)) if part.isdigit() else (1, part) for part in _NATURAL_SORT_DIGITS.split(name) if part]


def list_monitored_watchlists(session: Session) -> list[Watchlist]:
    """Every monitored watchlist (see MONITORED_WATCHLIST_PATTERN), in natural name order."""
    matched = [w for w in list_watchlists(session) if is_monitored_watchlist_name(w.name)]
    return sorted(matched, key=lambda w: _natural_name_key(w.name))


def list_monitored_tickers(session: Session) -> tuple[list[str], list[str]]:
    """Union of tickers across every monitored watchlist (visited in natural name order),
    deduped (first-seen order preserved) so a ticker on more than one list is only
    returned once. Shared by nightly_liquidity_zone_calculation.py,
    nightly_entry_signal_calculation.py, nightly_warren_signal_calculation.py and the
    daily-bars backfill.

    Returns (tickers, matched_names) so callers can log which watchlists were actually
    included -- there is no notion of a "missing" name, only however many (zero or more)
    watchlists happen to match right now."""
    matched = list_monitored_watchlists(session)
    seen: set[str] = set()
    tickers: list[str] = []
    for watchlist in matched:
        for row in list_watchlist_tickers(session, watchlist.id):
            if row.ticker not in seen:
                seen.add(row.ticker)
                tickers.append(row.ticker)
    return tickers, [w.name for w in matched]


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
    # child rows explicitly before the parent. Any SavedScreenerFilter that
    # scoped itself to this watchlist (Screener's WATCHLIST universe filter)
    # is deleted too, in the same transaction -- a saved view referencing a
    # gone watchlist_id would otherwise be a dangling reference with no
    # cleanup path of its own (see SavedScreenerFilter.watchlist_id's own
    # docstring).
    for ticker_row in list_watchlist_tickers(session, watchlist_id):
        session.delete(ticker_row)
    for saved_filter in session.exec(select(SavedScreenerFilter).where(SavedScreenerFilter.watchlist_id == watchlist_id)).all():
        session.delete(saved_filter)
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
    row = WatchlistTicker(watchlist_id=watchlist_id, ticker=normalize_ticker(ticker), added_at=datetime.now())
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
    for raw_ticker in tickers:
        ticker = normalize_ticker(raw_ticker)
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
