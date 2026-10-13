import re
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from core.models import EtfScreenerRow, SavedScreenerFilter, Watchlist, WatchlistTicker
from core.tickers import normalize_ticker
from data.etf_data import known_etf_tickers
from data.tracked_universe import load_delisted_flagged


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

def is_etf_watchlist(name: str) -> bool:
    """True for the one list that is ETF-only (exact, case-sensitive match, like the monitored rule)."""
    return name == ETF_WATCHLIST_NAME


def is_reserved_etf_list_name(name: str) -> bool:
    """True for any spelling of the ETF list's name that is not the exact name ("etf", "Etf", " ETF "): a
    list called that would look like the ETF list but be none (not monitored, no ETF-only guard). Rejected on
    create and rename."""
    return name != ETF_WATCHLIST_NAME and name.strip().casefold() == ETF_WATCHLIST_NAME.casefold()


def tickers_not_allowed_on_watchlist(session: Session, watchlist_name: str, tickers: Iterable[str]) -> list[str]:
    """The one rule for which tickers may join a list: any ticker may join any list except the ETF list, which
    holds ETFs only. Strict: a ticker must be a KNOWN ETF (data/etf_data.py::known_etf_tickers -- cached profile
    or score row says ETF/fund -- or a ticker with an EtfScreenerRow); a stock and a never-seen ticker are both
    refused. Returns the offending tickers, normalized, deduped, in first-seen order ([] when all may join)."""
    if not is_etf_watchlist(watchlist_name):
        return []
    names = list(dict.fromkeys(normalize_ticker(t) for t in tickers))
    if not names:
        return []
    known = known_etf_tickers(session, names) | set(
        session.exec(select(EtfScreenerRow.ticker).where(EtfScreenerRow.ticker.in_(names))).all()
    )
    return [t for t in names if t not in known]


def etf_only_message(offenders: list[str]) -> str:
    """The 400 text for tickers_not_allowed_on_watchlist's result."""
    subject = f"{offenders[0]} is not an ETF" if len(offenders) == 1 else f"{', '.join(offenders)} are not ETFs"
    return f'{subject}. The "{ETF_WATCHLIST_NAME}" watchlist holds ETFs only.'


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


def list_monitored_tickers_with_delisted(session: Session) -> tuple[list[str], list[str], list[str]]:
    """Union of tickers across every monitored watchlist (visited in natural name order),
    deduped (first-seen order preserved) so a ticker on more than one list is only
    returned once, **minus every delisted-flagged ticker** (TickerScore.delisted_at: out of
    every job, CLAUDE.md "Tracked universe"). Shared by nightly_liquidity_zone_calculation.py,
    nightly_entry_signal_calculation.py, nightly_warren_signal_calculation.py and the
    daily-bars backfill.

    Returns (tickers, matched_names, skipped_delisted): the matched names so callers can log
    which watchlists were actually included -- there is no notion of a "missing" name, only
    however many (zero or more) watchlists happen to match right now -- and the sorted
    delisted tickers that were left out, for a job that reports the count."""
    matched = list_monitored_watchlists(session)
    delisted = load_delisted_flagged(session)
    seen: set[str] = set()
    tickers: list[str] = []
    for watchlist in matched:
        for row in list_watchlist_tickers(session, watchlist.id):
            if row.ticker not in seen:
                seen.add(row.ticker)
                tickers.append(row.ticker)
    skipped = sorted(set(tickers) & delisted)
    return [t for t in tickers if t not in delisted], [w.name for w in matched], skipped


def list_monitored_tickers(session: Session) -> tuple[list[str], list[str]]:
    """(tickers, matched_names) of list_monitored_tickers_with_delisted, for a caller that does not
    report the delisted count. A delisted-flagged ticker is never returned."""
    tickers, matched_names, _skipped = list_monitored_tickers_with_delisted(session)
    return tickers, matched_names


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


class WatchlistCapacityExceeded(Exception):
    """Raised by the add helpers when `capacity` is given and the list would end up over it. Carries the numbers of the 400 message
    (`existing_count` before this add, `net_new_count` it would have added)."""

    def __init__(self, existing_count: int, net_new_count: int) -> None:
        super().__init__(f"{existing_count} + {net_new_count} is over the watchlist capacity")
        self.existing_count = existing_count
        self.net_new_count = net_new_count


def _member_count(session: Session, watchlist_id: int) -> int:
    return session.exec(select(func.count()).select_from(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist_id)).one()


def add_watchlist_ticker(session: Session, watchlist_id: int, ticker: str, *, capacity: int | None = None) -> WatchlistTicker:
    """Adds one member. With `capacity`, the cap is enforced INSIDE the write transaction: the insert is flushed first (which takes SQLite's
    write lock, so no other writer can slip in between), the members are counted, and the whole add is rolled back with
    `WatchlistCapacityExceeded` when it would pass the cap. The caller's earlier count is only the fast path; two concurrent adds to a list at
    capacity - 1 can no longer both succeed. A concurrent add of the same ticker raises `sqlalchemy.exc.IntegrityError` (the unique
    constraint); the caller rolls back and answers 409."""
    row = WatchlistTicker(watchlist_id=watchlist_id, ticker=normalize_ticker(ticker), added_at=datetime.now())
    session.add(row)
    if capacity is not None:
        session.flush()
        total = _member_count(session, watchlist_id)
        if total > capacity:
            session.rollback()
            raise WatchlistCapacityExceeded(total - 1, 1)
    session.commit()
    session.refresh(row)
    return row


def bulk_add_watchlist_tickers(
    session: Session, watchlist_id: int, tickers: list[str], *, capacity: int | None = None
) -> tuple[int, int]:
    """Adds every ticker not already a member, in one session/commit.
    Returns (added, already_present) so the caller can report e.g. "Added 47
    (3 already in this watchlist)" rather than erroring on the overlap --
    same dedupe the single-add endpoint already relies on via the unique
    constraint, just checked up front instead of racing the DB for it.
    Also naturally dedupes a caller-supplied list with repeats.

    With `capacity`, the cap is enforced inside the write transaction exactly as in `add_watchlist_ticker` (flush, count, roll back and raise
    `WatchlistCapacityExceeded`). If another request adds one of the same tickers between the membership read and the commit, the unique
    constraint fires: the transaction is rolled back and the whole add is retried once from a fresh membership read, so the overlap is
    reported as `already_present` like any other."""
    try:
        return _bulk_add_once(session, watchlist_id, tickers, capacity)
    except IntegrityError:
        session.rollback()
        return _bulk_add_once(session, watchlist_id, tickers, capacity)


def _bulk_add_once(session: Session, watchlist_id: int, tickers: list[str], capacity: int | None) -> tuple[int, int]:
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
    if capacity is not None and added:
        session.flush()
        total = _member_count(session, watchlist_id)
        if total > capacity:
            session.rollback()
            raise WatchlistCapacityExceeded(total - added, added)
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
