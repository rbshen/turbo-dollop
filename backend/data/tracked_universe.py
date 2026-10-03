"""The one definition of which tickers the nightly (and weekly) jobs process -- the "tracked
universe" -- and of when a page view counts toward it. Spec: docs/specs/tracked-universe.md.

`load_tracked_universe` is the STOCK side of `partition_known_tickers` (ETF cutover, 2026-10-03: the ETFs have their
own universe, `load_etf_universe`, refreshed by pipeline/nightly_etf_screener.py). A stock is in it when it is not
flagged delisted AND at least one of:

  (a) it is a member of the S&P 500, Nasdaq-100 or Dow list (`IndexConstituent`);
  (b) it is on ANY watchlist, monitored or not (`WatchlistTicker`);
  (c) its page was opened in the last `TRACKED_VIEW_WINDOW_DAYS` days (`TickerView`);
  (d) it carries manual data the owner entered: a Moat rating, a custom valuation, a bank-capital
      entry or a growth-catalyst note. Never expires, because the Monthly Momentum ranking is "Moat-rated tracked tickers" and
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
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from analysis.trend_structure.weinstein import WEINSTEIN_BENCHMARK_TICKER
from core.db import engine
from core.models import (
    FundamentalsCache,
    IndexConstituent,
    TickerScore,
    TickerView,
    Watchlist,
    WatchlistTicker,
    WeinsteinSettings,
)
from core.tickers import normalize_ticker
from data.etf_data import known_etf_tickers
from data.ticker_data_registry import MANUAL_DATA_LABELS, MANUAL_DATA_MODELS, WIPE_TABLES
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


def load_manual_data_tickers_by_table(session: Session) -> dict[str, set[str]]:
    """{table name: tickers} for each owner-entered per-ticker table (`ticker_data_registry.MANUAL_DATA_MODELS`:
    Moat, custom valuation, bank-capital entry, growth-catalyst note)."""
    return {
        model.__tablename__: set(session.exec(select(model.ticker)).all()) for model in MANUAL_DATA_MODELS
    }


def load_manual_data_tickers(session: Session) -> set[str]:
    """Rule (d): a Moat rating, any custom valuation (active or not: switching it off is not deleting
    the owner's work), a bank-capital entry, or a growth-catalyst note. The list of tables is the registry's
    `MANUAL_DATA_MODELS`, the one place a new user-entered table must be added."""
    tickers: set[str] = set()
    for found in load_manual_data_tickers_by_table(session).values():
        tickers |= found
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



def touch_existing_ticker_view(ticker: str, now: datetime | None = None) -> bool:
    """The START-of-request counterpart of `record_ticker_view` (opt-in universe step 3a): when the ticker already has a
    `TickerView` row, moves `last_viewed_at` forward at the very start of the summary request (at most once per
    calendar day), so a wipe cannot catch a ticker that is being opened. One UPDATE, no insert: a ticker with no row
    yet is created by `record_ticker_view` only after the summary succeeds (an invalid symbol never gets a row).
    Never touches `added_at` / `added_source`. Returns True when it wrote. Never raises."""
    now = now or datetime.now()
    ticker = normalize_ticker(ticker)
    start_of_day = datetime.combine(now.date(), time.min)
    try:
        stmt = (
            TickerView.__table__.update()
            .where(TickerView.__table__.c.ticker == ticker, TickerView.__table__.c.last_viewed_at < start_of_day)
            .values(last_viewed_at=now)
        )
        with Session(engine) as session:
            result = session.execute(stmt)
            session.commit()
        return result.rowcount > 0
    except Exception:  # noqa: BLE001 -- a view record is best-effort by design
        logger.warning("touch_existing_ticker_view failed for %s", ticker, exc_info=True)
        return False


def load_protection_reasons(session: Session, ticker: str) -> list[str]:
    """The DESIGN-state protections of one ticker, with detail, for the universe status API: `index:<name>` per index,
    `watchlist:<name>` per list, `seed`, `benchmark`, `rs_benchmark`, `manual:<label>` per owner-entered table. Same
    protections as `classify_wipe_candidates` (a test pins that they agree) but as targeted single-ticker reads, and
    without `added` (that is a state of its own, not a protection). Reads only."""
    ticker = normalize_ticker(ticker)
    reasons = [f"index:{name}" for name in sorted(set(session.exec(select(IndexConstituent.index_name).where(IndexConstituent.ticker == ticker)).all()))]
    lists = session.exec(
        select(Watchlist.name).join(WatchlistTicker, WatchlistTicker.watchlist_id == Watchlist.id).where(WatchlistTicker.ticker == ticker)
    ).all()
    reasons += [f"watchlist:{name}" for name in sorted(set(lists))]
    if ticker in ETF_SEED_TICKERS:
        reasons.append(PROTECTION_SEED)
    if ticker == WEINSTEIN_BENCHMARK_TICKER:
        reasons.append(PROTECTION_BENCHMARK)
    if ticker == read_rs_benchmark(session):
        reasons.append(PROTECTION_RS_BENCHMARK)
    for model in MANUAL_DATA_MODELS:
        if session.get(model, ticker) is not None:
            reasons.append(f"manual:{MANUAL_DATA_LABELS[model.__tablename__]}")
    return reasons


# --- the wipe (docs/specs/tracked-universe.md, "Planned: opt-in universe and wipe": NOT YET ACTIVE) --------------
# Pure decision logic for pipeline/wipe_untouched_tickers.py. It is computed from the RAW protection sets, never
# from `_classify` reasons: `_classify` answers "delisted" first, so a delisted ticker that is also on a watchlist
# would read as unprotected there. Nothing here writes; nothing here is read by a nightly job or a page yet, and the
# classification above is unchanged (a `TickerView` row with no added state still reads as "viewed").

WIPE_IDLE_DAYS = TRACKED_VIEW_WINDOW_DAYS  # the same 30 days: idle strictly MORE than this is due

DECISION_WIPE = "wipe"  # idle past the cutoff, unprotected, not added
DECISION_ADOPT = "adopt"  # has stored data, unprotected, and NO TickerView row: stamp it, never wipe blind
DECISION_PROTECTED = "protected"  # at least one protection (each is sufficient on its own)
DECISION_NOT_DUE = "not due"  # unprotected, has a TickerView row, idle for <= the cutoff
DECISION_IGNORED = "ignored"  # no stored data, no TickerView row, no protection (only seen via --tickers)

PROTECTION_INDEX = "index"
PROTECTION_WATCHLIST = "watchlist"
PROTECTION_SEED = "seed"
PROTECTION_BENCHMARK = "benchmark"  # WEINSTEIN_BENCHMARK_TICKER
PROTECTION_RS_BENCHMARK = "rs_benchmark"  # the live WeinsteinSettings.rs_benchmark value
PROTECTION_ADDED = "added"
PROTECTION_MANUAL_PREFIX = "manual:"  # + the table name, e.g. "manual:tickermoat"


@dataclass(frozen=True)
class WipeDecision:
    ticker: str
    decision: str
    protections: tuple[str, ...]
    last_viewed_at: datetime | None
    days_idle: float | None  # None when there is no TickerView row
    has_data: bool  # any row in a WIPE table other than TickerView (forex_rate rows never count)
    delisted: bool


def load_added_tickers(session: Session) -> set[str]:
    """Tickers the owner explicitly added (`TickerView.added_at` not null), stock and ETF alike. Read by the wipe
    (an added ticker is protected: it never expires by the 30-day rule). NOT read by `_classify` or any universe:
    until the classification flip ships, an added ticker is still in or out of the universe by the rules above."""
    return set(session.exec(select(TickerView.ticker).where(TickerView.added_at.is_not(None))).all())


def load_added_by_side(session: Session) -> tuple[set[str], set[str]]:
    """(added stocks, added ETFs), split by the same partition the two universes use. For the later steps (the ETF
    `EtfScreenerRow` write on Add, the flip); nothing reads it yet."""
    added = load_added_tickers(session)
    stocks, etfs = partition_known_tickers(session)
    return added & stocks, added & etfs


def load_any_index_tickers(session: Session) -> set[str]:
    """Every ticker in `IndexConstituent`, whatever its `index_name`. Wider than `load_index_tickers` (which is
    the three names the universe rule covers): a future index added to the table protects its members from the
    wipe without anyone remembering to touch this module."""
    return set(session.exec(select(IndexConstituent.ticker)).all())


def read_rs_benchmark(session: Session) -> str | None:
    """The live Weinstein RS benchmark. A plain read: `helpers.weinstein_config.get_weinstein_settings` seeds the
    row lazily (a write), which a dry run must never do, so the singleton row is read directly (None when
    the table has no row yet)."""
    row = session.get(WeinsteinSettings, "default")
    return normalize_ticker(row.rs_benchmark) if row is not None and row.rs_benchmark else None


def _tickers_with_data(session: Session, wanted: set[str] | None) -> set[str]:
    """Tickers holding at least one row in a WIPE table other than TickerView; `wanted` narrows the lookup. A
    FundamentalsCache row a table's `keep_where` names (forex_rate) never counts: its key is not a ticker."""
    if wanted is not None and not wanted:
        return set()
    inspector = inspect(session.get_bind())
    found: set[str] = set()
    params: dict = {}
    where_ticker = ""
    if wanted is not None:
        names = sorted(wanted)
        params = {f"t{i}": ticker for i, ticker in enumerate(names)}
        where_ticker = f"ticker IN ({', '.join(':' + key for key in params)})"
    for entry in WIPE_TABLES:
        if entry.name == TickerView.__tablename__ or not inspector.has_table(entry.name):
            continue
        clauses = [c for c in (where_ticker, f"NOT ({entry.keep_where})" if entry.keep_where else "") if c]
        sql = f'SELECT DISTINCT "{entry.key_column}" FROM "{entry.name}"' + (f" WHERE {' AND '.join(clauses)}" if clauses else "")
        found |= {row[0] for row in session.connection().execute(text(sql), params)}
    return found


def classify_wipe_candidates(
    session: Session,
    now: datetime | None = None,
    *,
    added: Iterable[str] = (),
    tickers: Iterable[str] | None = None,
) -> dict[str, WipeDecision]:
    """{ticker: WipeDecision} for every ticker the app holds state for (stored data or a TickerView row), or for
    exactly `tickers` when given. `added` is the set of explicitly added tickers (default empty: step 2 supplies the
    real loader); an added ticker is protected, because added tickers never expire by the 30-day rule.

    Order of evaluation: any protection -> protected; else no TickerView row -> adopt (stored data) or ignored (none);
    else idle strictly more than WIPE_IDLE_DAYS -> wipe; else not due. Delisted tickers follow the same rule (the
    flag is reported, never used): delisted + any protection stays, delisted unprotected idle > 30 days is wiped."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=WIPE_IDLE_DAYS)
    wanted = {normalize_ticker(t) for t in tickers} if tickers is not None else None

    index = load_any_index_tickers(session)
    watchlist = load_watchlist_tickers(session)
    seeds = set(ETF_SEED_TICKERS)
    benchmark = {WEINSTEIN_BENCHMARK_TICKER}
    rs = read_rs_benchmark(session)
    rs_benchmark = {rs} if rs else set()
    manual = load_manual_data_tickers_by_table(session)
    added_set = {normalize_ticker(t) for t in added}

    views = {row.ticker: row.last_viewed_at for row in session.exec(select(TickerView)).all()}
    stored = _tickers_with_data(session, wanted)
    delisted = load_delisted_flagged(session)

    universe = wanted if wanted is not None else (stored | set(views))
    decisions: dict[str, WipeDecision] = {}
    for ticker in sorted(universe):
        protections: list[str] = []
        if ticker in index:
            protections.append(PROTECTION_INDEX)
        if ticker in watchlist:
            protections.append(PROTECTION_WATCHLIST)
        if ticker in seeds:
            protections.append(PROTECTION_SEED)
        if ticker in benchmark:
            protections.append(PROTECTION_BENCHMARK)
        if ticker in rs_benchmark:
            protections.append(PROTECTION_RS_BENCHMARK)
        protections.extend(f"{PROTECTION_MANUAL_PREFIX}{table}" for table, found in sorted(manual.items()) if ticker in found)
        if ticker in added_set:
            protections.append(PROTECTION_ADDED)

        last_viewed = views.get(ticker)
        has_data = ticker in stored
        if protections:
            decision = DECISION_PROTECTED
        elif last_viewed is None:
            decision = DECISION_ADOPT if has_data else DECISION_IGNORED
        elif last_viewed < cutoff:
            decision = DECISION_WIPE
        else:
            decision = DECISION_NOT_DUE
        decisions[ticker] = WipeDecision(
            ticker=ticker,
            decision=decision,
            protections=tuple(protections),
            last_viewed_at=last_viewed,
            days_idle=(now - last_viewed).total_seconds() / 86400 if last_viewed is not None else None,
            has_data=has_data,
            delisted=ticker in delisted,
        )
    return decisions
