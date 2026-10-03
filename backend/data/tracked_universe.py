"""The one definition of which tickers the nightly (and weekly) jobs process -- the "tracked
universe" -- and of when a page view counts toward it. Spec: docs/specs/tracked-universe.md.

`load_tracked_universe` is the STOCK side of `partition_known_tickers` (ETF cutover, 2026-10-03: the ETFs have their
own universe, `load_etf_universe`, refreshed by pipeline/nightly_etf_screener.py). A stock is in it when it is not
flagged delisted AND at least one of:

  (a) it is a member of the S&P 500, Nasdaq-100 or Dow list (`IndexConstituent`);
  (b) it is on ANY watchlist, monitored or not (`WatchlistTicker`);
  (c) its page was opened in the last `TRACKED_VIEW_WINDOW_DAYS` days (`TickerView`);
  (d) it carries manual data the owner entered: a Moat rating, a custom valuation or a bank-capital
      entry. Never expires, because the Monthly Momentum ranking is "Moat-rated tracked tickers" and
      would otherwise silently shed them.
(The old "system set" rule, `SYSTEM_TICKERS` = the 11 sector ETFs plus SPY, is retired: those are ETFs, protected on the
ETF side by `ETF_SEED_TICKERS`.)

A ticker outside all of those is "expired": it stays in the DB with all its data (nothing is deleted),
it just drops out of the nightly jobs and the Screener's `all` universe until it is viewed again.
`load_all_known_tickers` is the old wide set (every ticker the app holds any row for) for the jobs
whose whole point is to see everything: the non-US purge, the delisted-flag sync and the search fallback.

**A future ETF momentum universe MUST be added to `ETF_SEED_TICKERS`** (and to the spec); the ETF momentum ranking is
"investigated, not built" (docs/specs/sector-heatmap.md). Protection, not insertion on the stock side: nothing here
creates a new row or a new FMP call.

Defined once, imported everywhere: `tests/test_tracked_universe.py` fails if a job or the Screener
re-declares the union or reads the old function names."""

import logging
from datetime import datetime, time, timedelta

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from analysis.trend_structure.weinstein import WEINSTEIN_BENCHMARK_TICKER
from core.db import engine
from core.models import (
    FundamentalsCache,
    IndexConstituent,
    TickerBankCapitalMetrics,
    TickerCustomValuation,
    TickerMoat,
    TickerScore,
    TickerView,
    WatchlistTicker,
)
from core.tickers import normalize_ticker
from data.etf_data import known_etf_tickers
from data.sector_heatmap_data import SECTOR_ETFS

logger = logging.getLogger(__name__)

TRACKED_VIEW_WINDOW_DAYS = 30

# The ETF-side universe's seed list (`load_etf_universe`): the tickers the app itself needs, not the owner: the 11
# SPDR sector ETFs (Sector Heatmap) and SPY (the Weinstein RS benchmark and the 5Y-vs-SPY comparison). Always in the
# ETF universe with reason "system", even when the app holds no profile for them yet. (Replaces the stock-side
# SYSTEM_TICKERS, retired at the cutover.) ADD A FUTURE ETF MOMENTUM UNIVERSE HERE.
ETF_SEED_TICKERS: frozenset[str] = frozenset(symbol for symbol, _ in SECTOR_ETFS) | {WEINSTEIN_BENCHMARK_TICKER}

# Why a known ticker is in or out. The first matching reason wins, in this order.
DELISTED = "delisted"
INDEX = "index"
WATCHLIST = "watchlist"
SYSTEM = "system"
MANUAL = "manual"
VIEWED = "viewed"
EXPIRED = "expired"
OUT_OF_UNIVERSE = frozenset({DELISTED, EXPIRED})


INDEX_NAMES = ("sp500", "dow", "nasdaq")  # IndexConstituent.index_name values rule (a) covers


def load_index_tickers(session: Session) -> set[str]:
    return set(session.exec(select(IndexConstituent.ticker).where(IndexConstituent.index_name.in_(INDEX_NAMES))).all())


def load_watchlist_tickers(session: Session) -> set[str]:
    return set(session.exec(select(WatchlistTicker.ticker)).all())


def load_all_known_tickers(session: Session) -> list[str]:
    """The old, wide "tracked" set: index constituents, any ticker with a cached FMP *profile* (not any
    FundamentalsCache ticker: that table also caches FX pairs such as EURUSD under ticker-shaped keys),
    any TickerScore row, any watchlist entry. Never expires and includes delisted tickers. For the
    purge, delisted-sync and search-fallback jobs only; everything that fetches uses
    `load_tracked_universe`."""
    profiles = session.exec(
        select(FundamentalsCache.ticker).where(FundamentalsCache.statement_type == "profile").distinct()
    ).all()
    scored = session.exec(select(TickerScore.ticker)).all()
    return sorted(load_index_tickers(session) | set(profiles) | set(scored) | load_watchlist_tickers(session))


def load_manual_data_tickers(session: Session) -> set[str]:
    """Rule (e): a Moat rating, any custom valuation (active or not: switching it off is not deleting
    the owner's work), or a bank-capital entry."""
    tickers: set[str] = set()
    for column in (TickerMoat.ticker, TickerCustomValuation.ticker, TickerBankCapitalMetrics.ticker):
        tickers |= set(session.exec(select(column)).all())
    return tickers


def load_delisted_flagged(session: Session) -> set[str]:
    return set(session.exec(select(TickerScore.ticker).where(TickerScore.delisted_at.is_not(None))).all())


def _classify(
    session: Session,
    known: set[str],
    now: datetime | None,
    *,
    index: set[str],
    manual: set[str],
    system: set[str],
) -> dict[str, str]:
    """The one first-match-wins classification, shared by the stock side (`classify_known_tickers`) and the
    ETF side (`classify_etf_tickers`). The caller decides which tickers are in play (`known`) and which of
    them each rule covers (`index`, `manual`, `system`); watchlist, view window and delisted flag are the
    same for both sides."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=TRACKED_VIEW_WINDOW_DAYS)
    watchlist = load_watchlist_tickers(session)
    viewed = set(session.exec(select(TickerView.ticker).where(TickerView.last_viewed_at >= cutoff)).all()) & known
    delisted = load_delisted_flagged(session)

    reasons: dict[str, str] = {}
    for ticker in known:
        if ticker in delisted:
            reasons[ticker] = DELISTED
        elif ticker in index:
            reasons[ticker] = INDEX
        elif ticker in watchlist:
            reasons[ticker] = WATCHLIST
        elif ticker in system:
            reasons[ticker] = SYSTEM
        elif ticker in manual:
            reasons[ticker] = MANUAL
        elif ticker in viewed:
            reasons[ticker] = VIEWED
        else:
            reasons[ticker] = EXPIRED
    return reasons


def classify_known_tickers(session: Session, now: datetime | None = None) -> dict[str, str]:
    """{ticker: reason} for every STOCK-side known ticker (ETFs are classified by `classify_etf_tickers`; the
    two sides are disjoint). A reason in OUT_OF_UNIVERSE (delisted, expired) means the nightly jobs skip it;
    any other reason means it is in. The single source for the universe, the Screener's hidden count and the
    verification report."""
    known, _ = partition_known_tickers(session)
    return _classify(
        session,
        known,
        now,
        index=load_index_tickers(session),
        manual=load_manual_data_tickers(session) & known,
        system=set(),
    )


def load_tracked_universe(session: Session, now: datetime | None = None) -> list[str]:
    """The sorted STOCK tickers every stock-side nightly and weekly job iterates (rules above). No ETF is in it."""
    reasons = classify_known_tickers(session, now)
    return sorted(t for t, reason in reasons.items() if reason not in OUT_OF_UNIVERSE)


def load_expired_tickers(session: Session, now: datetime | None = None) -> set[str]:
    """Known stocks, not delisted, but outside the universe because they were not viewed for 30 days."""
    return {t for t, reason in classify_known_tickers(session, now).items() if reason == EXPIRED}


# --- the ETF side (docs/specs/tracked-universe.md, "ETF universe") ----------------------------------------
# `partition_known_tickers` splits the wide known set; `load_tracked_universe` above is its stock side, the functions
# below its ETF side. Since the cutover (2026-10-03) the nightly ETF job (pipeline/nightly_etf_screener.py) owns the ETFs.


def partition_known_tickers(session: Session) -> tuple[set[str], set[str]]:
    """(stock side, ETF side) of the wide known set. A known ticker is on the ETF side when
    `known_etf_tickers` says so or it is an `ETF_SEED_TICKERS` member, otherwise on the stock side, so the
    two sides are disjoint and together hold every known ticker. The ETF side also carries the seeds the app
    has never seen (a seed needs no profile row)."""
    known = set(load_all_known_tickers(session))
    etfs = (set(known_etf_tickers(session, known)) if known else set()) | ETF_SEED_TICKERS
    return known - etfs, (known & etfs) | ETF_SEED_TICKERS


def classify_etf_tickers(session: Session, now: datetime | None = None) -> dict[str, str]:
    """{ticker: reason} for every ETF-side ticker. Same first-match rule as `classify_known_tickers`, minus the
    reasons that cannot apply to a fund: no index membership, no manual data (a Moat cannot be set on an ETF).
    An ETF on ANY watchlist (monitored or not) is in for as long as it stays there; a seed is "system"
    unless delisted; anything else is "viewed" within the 30-day window or "expired"."""
    _, etf_known = partition_known_tickers(session)
    return _classify(session, etf_known, now, index=set(), manual=set(), system=set(ETF_SEED_TICKERS))


def load_etf_universe(session: Session, now: datetime | None = None) -> list[str]:
    """The sorted ETF-side universe: every ETF-side ticker that is neither delisted nor expired."""
    reasons = classify_etf_tickers(session, now)
    return sorted(t for t, reason in reasons.items() if reason not in OUT_OF_UNIVERSE)


def load_expired_etfs(session: Session, now: datetime | None = None) -> set[str]:
    """Known ETFs, not delisted, outside the ETF universe because they were not viewed for 30 days."""
    return {t for t, reason in classify_etf_tickers(session, now).items() if reason == EXPIRED}


def count_hidden_inactive_etfs(session: Session, now: datetime | None = None) -> int:
    """How many ETFs the ETF universe hides as inactive: the ETF counterpart of `ScreenerMeta.hidden_inactive`
    (core/main.py::screener_meta counts the hidden stock rows). Counts expired ETFs, not rows of any table
    (the ETF read-model's own rows are not what is counted); a delisted ETF is not "inactive" and a seed never expires.
    `ScreenerMeta.hidden_inactive` counts expired STOCKS only, so the two never overlap (the sides are disjoint)."""
    return len(load_expired_etfs(session, now))


def record_ticker_view(ticker: str, now: datetime | None = None) -> bool:
    """Marks `ticker` as viewed now, at most once per calendar day: one statement, no pre-read, that
    inserts the row or moves `last_viewed_at` forward only when the stored value is from an earlier day.
    Returns True when it wrote. Never raises: a DB problem must not break the page that called it."""
    now = now or datetime.now()
    ticker = normalize_ticker(ticker)
    start_of_day = datetime.combine(now.date(), time.min)
    try:
        stmt = sqlite_insert(TickerView).values(ticker=ticker, last_viewed_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={"last_viewed_at": now},
            where=TickerView.__table__.c.last_viewed_at < start_of_day,
        )
        with Session(engine) as session:
            result = session.execute(stmt)
            session.commit()
        return result.rowcount > 0
    except Exception:  # noqa: BLE001 -- a view record is best-effort by design
        logger.warning("record_ticker_view failed for %s", ticker, exc_info=True)
        return False

