from datetime import date, timedelta

from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from core.models import FundamentalsCache
from core.schemas import (
    InsiderActivityOut,
    InsiderClusterBuy,
    InsiderNotableTradeOut,
    InsiderQuarterStatOut,
    InsiderSummaryOut,
    InsiderTransactionOut,
)
from core.tickers import normalize_ticker

# The trailing window is the N most recent quarterly statistics rows -- a
# "last 2 filed quarters" approximation, not a true rolling 6 months (the
# statistics endpoint only buckets by calendar quarter).
STATS_WINDOW_QUARTERS = 2

# 3+ distinct insiders buying on the open market within this span.
CLUSTER_BUY_MIN_INSIDERS = 3
CLUSTER_BUY_WINDOW_DAYS = 90

# How many search rows to request. FMP returns newest first, so for a busy
# ticker this bounds how far back the table/cluster check can see.
SEARCH_LIMIT = 100

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


def _num(value) -> float:
    """FMP numeric fields are sometimes null or absent; treat as 0."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


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

        out.append(
            InsiderTransactionOut(
                transaction_date=transaction_date,
                filing_date=_parse_date(row.get("filingDate")),
                insider_name=(row.get("reportingName") or "").strip() or _UNKNOWN_NAME,
                insider_cik=str(row["reportingCik"]).strip() if row.get("reportingCik") else None,
                insider_role=(row.get("typeOfOwner") or "").strip() or None,
                ownership={"D": "direct", "I": "indirect"}.get(direct_or_indirect),
                kind=kind,
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


async def get_insider_activity_data(ticker: str, cache_only: bool = False) -> InsiderActivityOut:
    """New, independent, read-only Insider Activity lens -- never touches
    Step 1-5/Overall Assessment scoring. Reads the standard
    FundamentalsCache blob shape (no dedicated table); Form 4s are
    event-driven, hence the dedicated insider_staleness_days window.

    `cache_only=True` (mirrors every other get_stepN_data function) reads
    only whatever's already cached and never calls FMP. FMP being paused is
    handled the same way by get_or_fetch itself (serves any cached row,
    however stale; a cold miss returns None) -- no special-casing here.
    """
    ticker = normalize_ticker(ticker)
    staleness_days = settings.insider_staleness_days

    with Session(engine) as session:
        search = await safe_fetch(
            "insider_trading_search",
            get_or_fetch(
                session,
                ticker,
                "insider_trading_search",
                "latest",
                lambda: fmp_client.get_insider_trading_search(ticker, SEARCH_LIMIT),
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

    transactions = normalize_transactions(search if isinstance(search, list) else [])
    quarterly_stats = normalize_quarterly_stats(statistics if isinstance(statistics, list) else [])

    return InsiderActivityOut(
        ticker=ticker,
        transactions=transactions,
        quarterly_stats=quarterly_stats,
        summary=build_summary(transactions, quarterly_stats),
        has_data=bool(transactions or quarterly_stats),
        as_of=as_of,
    )
