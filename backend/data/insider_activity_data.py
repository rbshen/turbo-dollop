import logging
from datetime import date, timedelta

import httpx
from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.data_groups import group_user_enabled
from core.db import engine
from core.models import FundamentalsCache
from core.schemas import (
    InsiderActivityOut,
    InsiderClusterBuy,
    InsiderNotableTradeOut,
    InsiderQuarterActivityOut,
    InsiderQuarterStatOut,
    InsiderSummaryOut,
    InsiderTransactionOut,
)
from core.tickers import normalize_ticker

logger = logging.getLogger(__name__)

# The trailing window is the N most recent quarterly statistics rows -- a
# "last 2 filed quarters" approximation, not a true rolling 6 months (the
# statistics endpoint only buckets by calendar quarter).
STATS_WINDOW_QUARTERS = 2

# 3+ distinct insiders buying on the open market within this span.
CLUSTER_BUY_MIN_INSIDERS = 3
CLUSTER_BUY_WINDOW_DAYS = 90

# The quarterly chart's window: this many calendar quarters ending at the
# newest transaction's quarter.
CHART_QUARTERS = 12

# /insider-trading/search paging. FMP orders rows by FILING date, newest
# first, so reaching back 12 quarters takes a lot of rows for a busy filer
# (measured live: AVGO ~600, FTNT ~1000, NVDA ~1600, META >3000 -- a single
# 100-row page covered under half a year for the first two). Per-request
# latency is ~1s regardless of page size, so pages are large to keep the
# round-trip count down, and paging stops as soon as the chart window is
# covered rather than at a fixed depth -- a quiet ticker costs one request.
# The page cap bounds the pathological tickers (cached blob ~550 KB per
# 1000 rows); a ticker that hits it is served as far back as it got, and the
# chart drops the quarters that would be incomplete (see
# build_quarterly_activity).
SEARCH_PAGE_SIZE = 500
SEARCH_MAX_PAGES = 4

# Cached blobs written before paging were one bare 100-row list. A full one
# was capped, not exhausted.
_LEGACY_SEARCH_LIMIT = 100

# FMP's transactionType is "<SEC Form 4 code>-<Label>" (e.g. "P-Purchase").
# The frontend only ever sees `kind` + a plain-language label, never these.
_KIND_BY_CODE = {
    "P": "open_market_buy",
    "S": "open_market_sale",
    "M": "option_exercise",
    "A": "award",
    "G": "gift",
}
_LABEL_BY_KIND = {
    "open_market_buy": "Open-market buy",
    "open_market_sale": "Open-market sale",
    "option_exercise": "Option exercise",
    "award": "Grant / award",
    "gift": "Gift",
}
# Plain-language labels for the remaining SEC Form 4 codes that fall into
# "other". An unrecognized code falls back to FMP's own label text.
_OTHER_LABEL_BY_CODE = {
    "C": "Derivative conversion",
    "D": "Disposed to issuer",
    "F": "Tax withholding",
    "I": "Discretionary transaction",
    "J": "Other",
    "K": "Equity swap",
    "L": "Small acquisition",
    "O": "Out-of-the-money exercise",
    "U": "Tender of shares",
    "W": "Will / inheritance",
    "X": "In-the-money exercise",
    "Z": "Trust deposit / withdrawal",
}


_UNKNOWN_NAME = "Unknown"

# An open-market buy is an acquisition and a sale a disposition by
# definition; every other kind reads FMP's own A/D flag.
_DIRECTION_BY_KIND = {"open_market_buy": "acquired", "open_market_sale": "disposed"}
_DIRECTION_BY_FLAG = {"A": "acquired", "D": "disposed"}


def _num(value) -> float:
    """FMP numeric fields are sometimes null or absent; treat as 0."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _quarter_index(d: date) -> int:
    return d.year * 4 + (d.month - 1) // 3


def _index_start(index: int) -> date:
    return date(index // 4, (index % 4) * 3 + 1, 1)


def _quarter_start(d: date, quarters_back: int = 0) -> date:
    """First day of the calendar quarter `quarters_back` quarters before d's."""
    return _index_start(_quarter_index(d) - quarters_back)


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _classify(transaction_type: str) -> tuple[str, str]:
    """(kind, plain-language label) for a non-empty FMP transactionType."""
    code, _, label_text = transaction_type.partition("-")
    code = code.strip().upper()
    kind = _KIND_BY_CODE.get(code, "other")
    if kind != "other":
        return kind, _LABEL_BY_KIND[kind]
    return kind, _OTHER_LABEL_BY_CODE.get(code) or label_text.strip() or "Other"


def normalize_transactions(rows: list) -> list[InsiderTransactionOut]:
    """Normalizes raw /insider-trading/search rows, newest first.

    Drops rows whose transactionType is empty (Form 3/5 position-only
    disclosures, not real transactions) and rows with no parseable
    transactionDate (can't be placed in the table or a cluster window).
    """
    out: list[InsiderTransactionOut] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        transaction_type = (row.get("transactionType") or "").strip()
        if not transaction_type:
            continue
        transaction_date = _parse_date(row.get("transactionDate"))
        if transaction_date is None:
            continue

        kind, label = _classify(transaction_type)
        price = _num(row.get("price"))
        shares = _num(row.get("securitiesTransacted"))
        # An award/gift/exercise at $0 has no cash value -- unlike an open-
        # market buy/sale, where $0 would be a data problem, not a fact.
        has_cash_value = kind in ("open_market_buy", "open_market_sale") or price > 0
        direct_or_indirect = (row.get("directOrIndirect") or "").strip().upper()
        direction = _DIRECTION_BY_KIND.get(kind) or _DIRECTION_BY_FLAG.get(
            (row.get("acquisitionOrDisposition") or "").strip().upper()
        )

        out.append(
            InsiderTransactionOut(
                transaction_date=transaction_date,
                filing_date=_parse_date(row.get("filingDate")),
                insider_name=(row.get("reportingName") or "").strip() or _UNKNOWN_NAME,
                insider_cik=str(row["reportingCik"]).strip() if row.get("reportingCik") else None,
                insider_role=(row.get("typeOfOwner") or "").strip() or None,
                ownership={"D": "direct", "I": "indirect"}.get(direct_or_indirect),
                kind=kind,
                direction=direction,
                type_label=label,
                shares=shares,
                price=price if price > 0 else None,
                has_cash_value=has_cash_value,
                dollar_value=price * shares if has_cash_value else None,
                sec_filing_url=row.get("secFilingUrl") or row.get("url") or None,
            )
        )
    out.sort(key=lambda t: (t.transaction_date, t.filing_date or date.min), reverse=True)
    _canonicalize_identities(out)
    return out


def _canonicalize_identities(newest_first: list[InsiderTransactionOut]) -> None:
    """One name and one role per reportingCik, in place.

    The same person's rows drift across filings: casing/punctuation variants
    of the name ("Hennessy John L." vs "HENNESSY JOHN L"), and a role/title
    that changes over time (or is blank on some filings). Every row for a CIK
    gets the value from its most recent row, so the table and the notable
    cards never disagree about who someone is.

    Name: the most recent row's own spelling, as filed -- not a synthetic
    re-casing, which would mangle names like "McDonald" or "O'Toole".
    Role: the most recent NON-BLANK one -- a filing with an empty typeOfOwner
    must not blank out a role every other filing carries. A name is "blank"
    only when it fell back to "Unknown". Rows with no CIK have no identity to
    unify and are left as they are."""
    name_by_cik: dict[str, str] = {}
    role_by_cik: dict[str, str] = {}
    for t in newest_first:
        if not t.insider_cik:
            continue
        if t.insider_name != _UNKNOWN_NAME:
            name_by_cik.setdefault(t.insider_cik, t.insider_name)
        if t.insider_role:
            role_by_cik.setdefault(t.insider_cik, t.insider_role)
    for t in newest_first:
        if t.insider_cik:
            t.insider_name = name_by_cik.get(t.insider_cik, t.insider_name)
            t.insider_role = role_by_cik.get(t.insider_cik, t.insider_role)


def normalize_quarterly_stats(rows: list) -> list[InsiderQuarterStatOut]:
    """Normalizes raw /insider-trading/statistics rows, oldest first."""
    out: list[InsiderQuarterStatOut] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        year, quarter = row.get("year"), row.get("quarter")
        if not isinstance(year, int) or not isinstance(quarter, int) or not 1 <= quarter <= 4:
            continue
        out.append(
            InsiderQuarterStatOut(
                year=year,
                quarter=quarter,
                total_acquired=_num(row.get("totalAcquired")),
                total_disposed=_num(row.get("totalDisposed")),
                total_purchases=_num(row.get("totalPurchases")),
                total_sales=_num(row.get("totalSales")),
            )
        )
    out.sort(key=lambda s: (s.year, s.quarter))
    return out


def build_quarterly_activity(
    transactions: list[InsiderTransactionOut], frontier: date | None
) -> tuple[list[InsiderQuarterActivityOut], bool]:
    """(chart series oldest first, history_truncated).

    Sums shares acquired/disposed per calendar quarter straight from the
    normalized transactions, bucketed by transactionDate. This replaces the
    statistics endpoint's totalAcquired/totalDisposed as the chart's source:
    those count exercises, tax withholding and gifts alongside real sales
    (overstating "selling" by roughly half on a typical quarter, 100% on
    some), and there was no way to split them. Open-market totals are the
    P/S rows only -- what the sentiment summary already uses; all-types adds
    every row that carries an acquired/disposed flag.

    The window is the CHART_QUARTERS calendar quarters ending at the newest
    transaction's quarter; a quarter with no rows inside it is a real zero.
    `frontier` (see _unpack_search_blob) is the oldest filing date fetched
    when the history stopped short of FMP's own; a quarter is only shown if
    it begins after it, since an earlier one could be missing rows -- and a
    partly-filled bar reads as a real, smaller total. When that trims the
    window, `history_truncated` is True. With the history exhausted
    (frontier None), quarters before the first-ever transaction aren't
    plotted as zeros."""
    if not transactions:
        return [], False
    newest = _quarter_index(transactions[0].transaction_date)  # newest first
    window_first = newest - (CHART_QUARTERS - 1)

    first = window_first
    if frontier is None:
        first = max(first, _quarter_index(transactions[-1].transaction_date))
    else:
        while first <= newest and _index_start(first) <= frontier:
            first += 1
    truncated = frontier is not None and first > window_first

    buckets = {index: [0.0, 0.0, 0.0, 0.0] for index in range(first, newest + 1)}
    for t in transactions:
        bucket = buckets.get(_quarter_index(t.transaction_date))
        if bucket is None:
            continue
        if t.kind == "open_market_buy":
            bucket[0] += t.shares
        elif t.kind == "open_market_sale":
            bucket[1] += t.shares
        if t.direction == "acquired":
            bucket[2] += t.shares
        elif t.direction == "disposed":
            bucket[3] += t.shares

    series = [
        InsiderQuarterActivityOut(
            year=index // 4,
            quarter=index % 4 + 1,
            open_market_acquired=b[0],
            open_market_disposed=b[1],
            all_acquired=b[2],
            all_disposed=b[3],
        )
        for index, b in buckets.items()
    ]
    return series, truncated


def classify_sentiment(total_purchases: float, total_sales: float) -> str:
    """First-pass rule -- a direct comparison of summed purchases vs sales,
    no materiality threshold. Easy to retune here later (e.g. a ratio band
    around "mixed")."""
    if total_purchases == 0 and total_sales == 0:
        return "no_activity"
    if total_purchases > total_sales:
        return "net_buying"
    if total_sales > total_purchases:
        return "net_selling"
    return "mixed"


def find_cluster_buy(transactions: list[InsiderTransactionOut]) -> InsiderClusterBuy | None:
    """Most recent window in which 3+ distinct insiders (reportingCik, name
    as a fallback key) made open-market buys within CLUSTER_BUY_WINDOW_DAYS
    of each other. A window is anchored on each buy's own date and looks
    back, so the first anchor (scanning newest first) that qualifies is the
    most recent qualifying window."""
    buys = [t for t in transactions if t.kind == "open_market_buy"]  # already newest first
    for anchor in buys:
        cutoff = anchor.transaction_date - timedelta(days=CLUSTER_BUY_WINDOW_DAYS)
        in_window = [t for t in buys if cutoff <= t.transaction_date <= anchor.transaction_date]
        insiders = {t.insider_cik or t.insider_name for t in in_window}
        if len(insiders) >= CLUSTER_BUY_MIN_INSIDERS:
            return InsiderClusterBuy(
                insider_count=len(insiders),
                window_start=min(t.transaction_date for t in in_window),
                window_end=anchor.transaction_date,
            )
    return None


def _largest_same_day(transactions: list[InsiderTransactionOut], kind: str) -> InsiderNotableTradeOut | None:
    """The largest open-market trade of `kind`, with same-day lines by the
    same insider merged first. Form 4 routinely splits one real sale into
    many price-band lines, so the single largest LINE understates the trade
    (AVGO: ~$40M line vs. a $250M same-day total across 22 lines).

    Grouped by (reportingCik, transactionDate) only -- deliberately no wider
    window, so separate 10b5-1 drip sales on different days stay distinct
    events. Rows without a CIK fall back to the name as the insider key,
    matching find_cluster_buy."""
    groups: dict[tuple[str, date], list[InsiderTransactionOut]] = {}
    for t in transactions:
        if t.kind == kind:
            groups.setdefault((t.insider_cik or t.insider_name, t.transaction_date), []).append(t)

    best: tuple[float, list[InsiderTransactionOut]] | None = None
    for lines in groups.values():
        total = sum(t.dollar_value or 0 for t in lines)
        if total > 0 and (best is None or total > best[0]):
            best = (total, lines)
    if best is None:
        return None

    total_dollars, lines = best
    total_shares = sum(t.shares for t in lines)
    largest_line = max(lines, key=lambda t: t.dollar_value or 0)
    ownerships = {t.ownership for t in lines}
    return InsiderNotableTradeOut(
        **{
            **largest_line.model_dump(),
            "shares": total_shares,
            "price": total_dollars / total_shares if total_shares > 0 else None,
            "has_cash_value": True,
            "dollar_value": total_dollars,
            "ownership": ownerships.pop() if len(ownerships) == 1 else None,
            "fill_count": len(lines),
        }
    )


def build_summary(
    transactions: list[InsiderTransactionOut], quarterly_stats: list[InsiderQuarterStatOut]
) -> InsiderSummaryOut:
    window = quarterly_stats[-STATS_WINDOW_QUARTERS:]
    total_purchases = sum(s.total_purchases for s in window)
    total_sales = sum(s.total_sales for s in window)

    if window:
        earliest = window[0]
        window_start: date | None = date(earliest.year, (earliest.quarter - 1) * 3 + 1, 1)
        in_window = [t for t in transactions if t.transaction_date >= window_start]
    else:
        in_window = transactions

    return InsiderSummaryOut(
        sentiment=classify_sentiment(total_purchases, total_sales),
        quarters_in_window=len(window),
        total_purchases=total_purchases,
        total_sales=total_sales,
        total_acquired=sum(s.total_acquired for s in window),
        total_disposed=sum(s.total_disposed for s in window),
        open_market_buy_count=sum(1 for t in in_window if t.kind == "open_market_buy"),
        open_market_sale_count=sum(1 for t in in_window if t.kind == "open_market_sale"),
        cluster_buy=find_cluster_buy(transactions),
        notable_buy=_largest_same_day(transactions, "open_market_buy"),
        notable_sale=_largest_same_day(transactions, "open_market_sale"),
    )


def _filing_frontier(rows: list) -> date | None:
    """Oldest filing date among the fetched rows (transactionDate as a
    fallback for a row with no usable filingDate). FMP pages by filing date,
    newest first, so every row NOT fetched was filed on or before this --
    and a filing is never earlier than its own transaction, so it also
    bounds the unfetched rows' transaction dates."""
    dates = [
        d
        for row in rows
        if isinstance(row, dict)
        for d in [_parse_date(row.get("filingDate")) or _parse_date(row.get("transactionDate"))]
        if d is not None
    ]
    return min(dates, default=None)


def _covers_chart_window(rows: list, frontier: date | None) -> bool:
    """True once everything unfetched must fall before the chart window --
    i.e. the frontier sits before the window's first day. (Not `min` over
    transactionDate: a stray old Form 5 row inside a recent page would end
    the paging early.)"""
    transactions = normalize_transactions(rows)
    if frontier is None or not transactions:
        return False
    return frontier < _quarter_start(transactions[0].transaction_date, CHART_QUARTERS - 1)


async def _fetch_search_history(ticker: str) -> dict | list:
    """Pages through /insider-trading/search until the chart window is
    covered, FMP runs out of rows, or SEARCH_MAX_PAGES is hit.

    Returns the cached blob `{"rows": [...], "exhausted": bool}` -- `exhausted`
    is what tells "FMP has nothing older" (a quiet ticker) apart from "we
    stopped fetching" (the cap), which decides whether quarters older than
    the fetched rows are genuinely empty or just unseen. A first-page failure
    propagates (safe_fetch turns it into a cold miss, nothing cached, same as
    before); a failure on a later page keeps what was fetched and reports it
    as not exhausted, rather than discarding a usable history over a blip.
    """
    rows: list = []
    for page in range(SEARCH_MAX_PAGES):
        try:
            batch = await fmp_client.get_insider_trading_search(ticker, SEARCH_PAGE_SIZE, page)
        except httpx.HTTPError:
            if page == 0:
                raise
            logger.warning("insider search page %d failed for %s; keeping %d rows", page, ticker, len(rows))
            return {"rows": rows, "exhausted": False}
        if not isinstance(batch, list):
            if page == 0:
                return batch  # an error/unexpected payload -- read as empty downstream
            return {"rows": rows, "exhausted": False}
        rows.extend(batch)
        if len(batch) < SEARCH_PAGE_SIZE:
            return {"rows": rows, "exhausted": True}
        if _covers_chart_window(rows, _filing_frontier(rows)):
            return {"rows": rows, "exhausted": False}
    logger.warning("insider search for %s hit the %d-page cap without covering the chart window", ticker, SEARCH_MAX_PAGES)
    return {"rows": rows, "exhausted": False}


def _unpack_search_blob(blob) -> tuple[list, date | None]:
    """(rows, frontier) from a cached search blob. `frontier` is None when the
    history is complete (FMP was exhausted); otherwise the oldest filing date
    fetched -- rows filed on or before it may be missing."""
    if isinstance(blob, dict) and isinstance(blob.get("rows"), list):
        rows, exhausted = blob["rows"], bool(blob.get("exhausted"))
    elif isinstance(blob, list):
        # Pre-paging blob: a full 100-row list was capped, a shorter one exhausted.
        rows, exhausted = blob, len(blob) < _LEGACY_SEARCH_LIMIT
    else:
        return [], None
    if exhausted:
        return rows, None
    return rows, _filing_frontier(rows) or date.max


async def get_insider_activity_data(ticker: str, cache_only: bool = False) -> InsiderActivityOut:
    """New, independent, read-only Insider Activity lens -- never touches
    Step 1-5/Overall Assessment scoring. Reads the standard
    FundamentalsCache blob shape (no dedicated table); Form 4s are
    event-driven, hence the dedicated insider_staleness_days window.

    `cache_only=True` (mirrors every other get_stepN_data function) reads
    only whatever's already cached and never calls FMP. FMP being paused is
    handled the same way by get_or_fetch itself (serves any cached row,
    however stale; a cold miss returns None) -- no special-casing here.

    Shelved feature: when the `insider` data group is not live (seeded off; see core/data_groups.py) this
    returns a distinct `enabled=False` payload before touching FMP, the
    cache or the DB at all -- checked first, ahead of `cache_only`, so not
    even a cache read happens. The GET route just calls this function, so it
    inherits the gate.
    """
    ticker = normalize_ticker(ticker)
    if not group_user_enabled("insider"):
        return InsiderActivityOut(
            ticker=ticker,
            enabled=False,
            transactions=[],
            quarterly_stats=[],
            summary=build_summary([], []),
            has_data=False,
            as_of=None,
        )
    staleness_days = settings.insider_staleness_days

    with Session(engine) as session:
        search = await safe_fetch(
            "insider_trading_search",
            get_or_fetch(
                session,
                ticker,
                "insider_trading_search",
                "latest",
                lambda: _fetch_search_history(ticker),
                staleness_days,
                cache_only,
            ),
        )
        statistics = await safe_fetch(
            "insider_trading_statistics",
            get_or_fetch(
                session,
                ticker,
                "insider_trading_statistics",
                "latest",
                lambda: fmp_client.get_insider_trading_statistics(ticker),
                staleness_days,
                cache_only,
            ),
        )
        # fetched_at of the cached search row, re-read directly (get_or_fetch
        # only returns the payload) -- the only thing that tells "cached and
        # genuinely empty" (HK/France/quiet tickers) apart from "never
        # successfully cached" (cold miss: FMP paused, or the fetch failed).
        search_row = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == ticker,
                FundamentalsCache.statement_type == "insider_trading_search",
                FundamentalsCache.period == "latest",
            )
        ).first()
        as_of = search_row.fetched_at if search_row else None

    search_rows, search_frontier = _unpack_search_blob(search)
    transactions = normalize_transactions(search_rows)
    quarterly_stats = normalize_quarterly_stats(statistics if isinstance(statistics, list) else [])

    quarterly_activity, history_truncated = build_quarterly_activity(transactions, search_frontier)

    return InsiderActivityOut(
        ticker=ticker,
        transactions=transactions,
        quarterly_stats=quarterly_stats,
        quarterly_activity=quarterly_activity,
        history_truncated=history_truncated,
        summary=build_summary(transactions, quarterly_stats),
        has_data=bool(transactions or quarterly_stats),
        as_of=as_of,
    )
