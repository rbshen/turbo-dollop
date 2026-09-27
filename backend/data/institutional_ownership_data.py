"""Institutional Ownership ticker-page tab -- FMP's 13F-derived
symbol-positions-summary (one row per quarter: ownership %, holder count,
opened/increased/reduced/closed position counts, each with a ready-made
QoQ delta) and extract-analytics/holder (per-holder market value/shares,
already sorted descending by market value). See the feasibility
investigation this implementation is based on for the full field mapping
and the data-quality findings behind the plausibility guardrail below.

Four states the caller must distinguish (InstitutionalOwnershipOut):
  (a) the `institutional_ownership` data group is off -- `enabled=False`,
      nothing fetched at all (no cache read, no FMP call);
  (b) genuinely no 13F coverage for this ticker (every quarter in the
      anchor-search window comes back an empty list) -- `no_coverage=True`;
  (c) the LATEST quarter fails the plausibility guardrail -- the headline
      stat cards + sentiment badge degrade to `note`, but `positions` and
      `top_holders` still render (computed independently); an OLDER quarter
      failing the guardrail just drops that one point from `trend`
      (`trend_quarters_shown` reports how many of the 8 slots survived);
  (d) a normal complete read.

Neither `year`+`quarter` is optional on FMP's own symbol-positions-summary
endpoint (a 400 without both) and there is no bulk/multi-quarter mode -- one
call per quarter, confirmed live during the feasibility investigation.
"""

import logging
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.data_groups import group_live
from core.db import engine
from core.models import FundamentalsCache
from core.schemas import (
    InstitutionalHolderOut,
    InstitutionalOwnershipOut,
    InstitutionalOwnershipPositionsOut,
    InstitutionalOwnershipQuarterOut,
)
from core.tickers import normalize_ticker
from helpers.first import _first
from helpers.shares import compute_shares_outstanding
from helpers.ttm import TOTAL_QUARTERS_NEEDED

logger = logging.getLogger(__name__)

GROUP = "institutional_ownership"

# How many quarters the trend chart shows, and how far back we'll walk from
# today's calendar quarter looking for the first one FMP has actually filed
# data for (13F filings lag up to 45 days, plus a trickle of late filers --
# confirmed live during the feasibility investigation that even the
# genuinely in-progress current quarter reads as a clean empty list, not a
# partial row). 4 is a generous safety margin over the 1-2 quarters real
# data ever needed in testing.
TREND_QUARTERS = 8
ANCHOR_SEARCH_MAX_QUARTERS = 4

TOP_HOLDERS_LIMIT = 15
SENTIMENT_LOOKBACK_QUARTERS = 4

# Dedicated staleness window for this feature -- mirrors the old
# insider_staleness_days convention (a per-feature constant distinct from
# the shared settings.cache_staleness_days default) rather than reusing
# the shared fundamentals cadence. This is the window get_or_fetch itself
# checks (how often a refetch is even ATTEMPTED); REFETCH_WINDOW_DAYS below
# is the separate, coarser gate on WHETHER a refetch is attempted at all
# for a given quarter.
INSTITUTIONAL_OWNERSHIP_STALENESS_DAYS = 7

# SEC's own 13F filing deadline is 45 calendar days after quarter-end, but
# real filings trickle in well past it (confirmed live: an AAPL holder's
# filingDate landed ~5.5 weeks after that deadline) -- so a quarter is kept
# in the normal ~weekly refetch rotation through 45 + 56 (~8 weeks) days
# past its own quarter-end, then treated as settled: once a row already
# exists for that quarter, it's served frozen (no further live attempts)
# rather than refetched forever on the flat clock above. A quarter with NO
# cached row yet is always fetched at least once regardless of how old it
# is -- this gate only stops REPEATED attempts of an already-cached row.
FILING_DEADLINE_DAYS = 45
REFETCH_GRACE_DAYS = 56

# Plausibility guardrail thresholds (see the feasibility investigation):
# FMP's own ownershipPercent read >100% for ARES's Q2 2026 row, and the
# implied shares-outstanding it backs into (numberOf13Fshares /
# (ownershipPercent/100)) diverges from Fathom's own figure on dual-class/
# GP-LP names (IBKR read as if ~87% of TOTAL shares were institutionally
# held, implausible for a company where insiders hold the majority).
OWNERSHIP_PCT_MAX = 98.0
SHARES_OUTSTANDING_DIVERGENCE_THRESHOLD = 0.15

# On top of, not instead of, the normal ~weekly cache-refetch attempts
# below -- 13F filings trickle in well past the nominal 45-day deadline
# (confirmed live: an AAPL holder's filingDate landed ~5.5 weeks after that
# quarter's own deadline), so this only fires for the rarer case of the
# data going stale well beyond even that trickle window.
STALE_WARNING_DAYS = 120

DEGRADED_NOTE = (
    "This quarter's institutional-ownership figures look unreliable (an FMP "
    "data anomaly) and have been hidden; positions and top holders below "
    "are computed independently and are unaffected."
)


def _calendar_quarter(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def _quarter_before(year: int, quarter: int) -> tuple[int, int]:
    return (year, quarter - 1) if quarter > 1 else (year - 1, 4)


def _quarter_label(year: int, quarter: int) -> str:
    return f"{year}Q{quarter}"


def _quarter_end_date(year: int, quarter: int) -> date:
    month = quarter * 3
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _past_refetch_window(year: int, quarter: int, today: date | None = None) -> bool:
    """True once we're more than FILING_DEADLINE_DAYS + REFETCH_GRACE_DAYS
    past that quarter's own end date -- see the constants' own comment."""
    today = today or date.today()
    return today > _quarter_end_date(year, quarter) + timedelta(days=FILING_DEADLINE_DAYS + REFETCH_GRACE_DAYS)


def _cached_row(session: Session, ticker: str, statement_type: str, period: str) -> FundamentalsCache | None:
    return session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker,
            FundamentalsCache.statement_type == statement_type,
            FundamentalsCache.period == period,
        )
    ).first()


def _effective_cache_only(session: Session, ticker: str, statement_type: str, year: int, quarter: int, cache_only: bool) -> bool:
    """A quarter already past its own refetch-grace window is served frozen
    -- once cached, never live-refetched again -- regardless of how stale
    the flat INSTITUTIONAL_OWNERSHIP_STALENESS_DAYS clock says it is. A
    quarter with no cached row yet is always fetched at least once, no
    matter how old, since this gate only stops REPEATING an attempt, not
    the first one."""
    if cache_only:
        return True
    label = _quarter_label(year, quarter)
    existing = _cached_row(session, ticker, statement_type, label)
    return existing is not None and _past_refetch_window(year, quarter)


async def _fetch_summary_quarter(session: Session, ticker: str, year: int, quarter: int, cache_only: bool) -> list[dict]:
    label = _quarter_label(year, quarter)
    effective_cache_only = _effective_cache_only(session, ticker, "institutional_ownership_summary", year, quarter, cache_only)
    data = await safe_fetch(
        f"institutional_ownership_summary_{label}",
        get_or_fetch(
            session,
            ticker,
            "institutional_ownership_summary",
            label,
            lambda: fmp_client.get_institutional_ownership_summary(ticker, year, quarter),
            INSTITUTIONAL_OWNERSHIP_STALENESS_DAYS,
            effective_cache_only,
        ),
    )
    # A real empty list ("not yet filed") and safe_fetch's own {} failure
    # fallback both normalize to [] here, deliberately -- callers must treat
    # neither as an error (see module docstring).
    return data if isinstance(data, list) else []


async def _fetch_holders(session: Session, ticker: str, year: int, quarter: int, cache_only: bool) -> list[dict]:
    label = _quarter_label(year, quarter)
    effective_cache_only = _effective_cache_only(session, ticker, "institutional_ownership_holders", year, quarter, cache_only)
    data = await safe_fetch(
        f"institutional_ownership_holders_{label}",
        get_or_fetch(
            session,
            ticker,
            "institutional_ownership_holders",
            label,
            lambda: fmp_client.get_institutional_ownership_holders(ticker, year, quarter, page=0, limit=TOP_HOLDERS_LIMIT),
            INSTITUTIONAL_OWNERSHIP_STALENESS_DAYS,
            effective_cache_only,
        ),
    )
    return data if isinstance(data, list) else []


def _quarter_is_plausible(row: dict, shares_outstanding: float | None) -> bool:
    pct = row.get("ownershipPercent")
    if pct is None:
        return False
    if pct < 0 or pct > OWNERSHIP_PCT_MAX:
        return False
    n13f = row.get("numberOf13Fshares")
    if shares_outstanding and n13f and pct > 0:
        implied = n13f / (pct / 100.0)
        if abs(implied - shares_outstanding) / shares_outstanding > SHARES_OUTSTANDING_DIVERGENCE_THRESHOLD:
            return False
    return True


def _to_quarter_out(year: int, quarter: int, row: dict) -> InstitutionalOwnershipQuarterOut:
    return InstitutionalOwnershipQuarterOut(
        year=year,
        quarter=quarter,
        date=row.get("date"),
        ownership_percent=row.get("ownershipPercent"),
        ownership_percent_change=row.get("ownershipPercentChange"),
        investors_holding=row.get("investorsHolding"),
        investors_holding_change=row.get("investorsHoldingChange"),
    )


def _build_positions(row: dict) -> InstitutionalOwnershipPositionsOut | None:
    fields = ("newPositions", "increasedPositions", "reducedPositions", "closedPositions")
    if any(row.get(f) is None for f in fields):
        return None
    return InstitutionalOwnershipPositionsOut(
        opened=row["newPositions"],
        opened_change=row.get("newPositionsChange"),
        increased=row["increasedPositions"],
        increased_change=row.get("increasedPositionsChange"),
        reduced=row["reducedPositions"],
        reduced_change=row.get("reducedPositionsChange"),
        closed=row["closedPositions"],
        closed_change=row.get("closedPositionsChange"),
    )


def _to_holder_out(row: dict) -> InstitutionalHolderOut:
    return InstitutionalHolderOut(
        investor_name=row.get("investorName") or "",
        market_value=row.get("marketValue"),
        market_value_change_pct=row.get("changeInMarketValuePercentage"),
        shares=row.get("sharesNumber"),
        shares_change_pct=row.get("changeInSharesNumberPercentage"),
    )


def _compute_sentiment(recent: list[InstitutionalOwnershipQuarterOut]) -> tuple[str | None, int]:
    """Accumulating if >=3 of the (up to) last 4 quarters have a positive
    ownershipPercentChange; Distributing if >=3 are negative; otherwise
    Neutral. `recent` is expected to already be latest-first and already
    filtered to present+plausible quarters (i.e. `trend`'s own leading
    slice) -- a quarter dropped by the guardrail simply isn't in the pool
    either bucket draws from."""
    changes = [q.ownership_percent_change for q in recent if q.ownership_percent_change is not None]
    rising = sum(1 for c in changes if c > 0)
    falling = sum(1 for c in changes if c < 0)
    if rising >= 3:
        return "Accumulating", rising
    if falling >= 3:
        return "Distributing", rising
    return "Neutral", rising


def _empty_out(ticker: str, *, enabled: bool, no_coverage: bool) -> InstitutionalOwnershipOut:
    return InstitutionalOwnershipOut(
        ticker=ticker,
        enabled=enabled,
        no_coverage=no_coverage,
        ownership_valid=False,
        trend_quarters_total=TREND_QUARTERS,
    )


async def get_institutional_ownership_data(ticker: str, cache_only: bool = False) -> InstitutionalOwnershipOut:
    ticker = normalize_ticker(ticker)

    if not group_live(GROUP):
        # Hard gate, ahead of any cache read -- see module docstring state (a).
        return _empty_out(ticker, enabled=False, no_coverage=False)

    # Only for the two shared cache keys below (quote/income_statement) --
    # the two institutional-ownership endpoints use their own dedicated
    # INSTITUTIONAL_OWNERSHIP_STALENESS_DAYS instead (see _fetch_summary_quarter/
    # _fetch_holders).
    shared_staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        anchor: tuple[int, int] | None = None
        anchor_row: dict | None = None
        year, quarter = _calendar_quarter(date.today())
        for _ in range(ANCHOR_SEARCH_MAX_QUARTERS):
            rows = await _fetch_summary_quarter(session, ticker, year, quarter, cache_only)
            if rows:
                anchor, anchor_row = (year, quarter), rows[0]
                break
            year, quarter = _quarter_before(year, quarter)

        if anchor is None or anchor_row is None:
            return _empty_out(ticker, enabled=True, no_coverage=True)

        anchor_year, anchor_quarter = anchor

        # Same "re-read the cache row directly for its fetched_at" convention
        # analyst_ratings_data.py uses for grades_consensus_row -- get_or_fetch
        # itself only returns the parsed payload, not this metadata.
        anchor_cache_row = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == ticker,
                FundamentalsCache.statement_type == "institutional_ownership_summary",
                FundamentalsCache.period == _quarter_label(anchor_year, anchor_quarter),
            )
        ).first()
        fetched_at = anchor_cache_row.fetched_at if anchor_cache_row else None

        # Fathom's own shares-outstanding figure (never FMP's derived one --
        # see InstitutionalOwnershipOut's own docstring). Reuses the exact
        # shared cache keys ticker_summary.py/step3_data.py/
        # analyst_ratings_data.py already populate -- zero new fetch shape,
        # and a cold fetch here matches their own limit so it never leaves a
        # thinner cached row than what those tabs expect.
        quote = _first(
            await safe_fetch(
                "quote",
                get_or_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker), shared_staleness_days, cache_only),
            )
        )
        income_quarterly_data = await safe_fetch(
            "income_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "income_statement",
                "quarterly",
                lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                shared_staleness_days,
                cache_only,
            ),
        )
        income_quarterly = income_quarterly_data if isinstance(income_quarterly_data, list) else []
        shares_outstanding, shares_outstanding_source = compute_shares_outstanding(quote, income_quarterly)

        # Walk the 8-quarter trend backward from the anchor. Re-uses one
        # Fathom shares_outstanding figure across the whole window (a rough
        # but deliberate simplification -- the 15% divergence threshold
        # gives generous room for organic share-count drift over ~2 years;
        # computing a distinct historical shares-outstanding per quarter
        # would need a fetch per quarter of its own, which the guardrail's
        # purpose doesn't call for).
        trend: list[InstitutionalOwnershipQuarterOut] = []
        y, q = anchor_year, anchor_quarter
        for i in range(TREND_QUARTERS):
            row = anchor_row if i == 0 else None
            if row is None:
                rows = await _fetch_summary_quarter(session, ticker, y, q, cache_only)
                row = rows[0] if rows else None
            if row is not None and _quarter_is_plausible(row, shares_outstanding):
                trend.append(_to_quarter_out(y, q, row))
            y, q = _quarter_before(y, q)

        ownership_valid = bool(trend) and trend[0].year == anchor_year and trend[0].quarter == anchor_quarter
        latest = trend[0] if ownership_valid else None

        note = None if ownership_valid else DEGRADED_NOTE

        sentiment: str | None = None
        rising_count: int | None = None
        if ownership_valid:
            sentiment, rising_count = _compute_sentiment(trend[:SENTIMENT_LOOKBACK_QUARTERS])

        # Independent of ownership_valid -- see module/schema docstrings.
        positions = _build_positions(anchor_row)
        holders_raw = await _fetch_holders(session, ticker, anchor_year, anchor_quarter, cache_only)
        top_holders = [_to_holder_out(h) for h in holders_raw]

        data_stale_warning = fetched_at is not None and (datetime.now() - fetched_at) > timedelta(days=STALE_WARNING_DAYS)

    return InstitutionalOwnershipOut(
        ticker=ticker,
        enabled=True,
        no_coverage=False,
        as_of_quarter=_quarter_label(anchor_year, anchor_quarter),
        as_of_date=anchor_row.get("date"),
        fetched_at=fetched_at,
        data_stale_warning=data_stale_warning,
        ownership_valid=ownership_valid,
        ownership_percent=latest.ownership_percent if latest else None,
        ownership_percent_change=latest.ownership_percent_change if latest else None,
        holder_count=latest.investors_holding if latest else None,
        holder_count_change=latest.investors_holding_change if latest else None,
        shares_held=anchor_row.get("numberOf13Fshares") if ownership_valid else None,
        shares_outstanding=shares_outstanding,
        shares_outstanding_source=shares_outstanding_source,
        sentiment=sentiment,
        sentiment_rising_count=rising_count,
        positions=positions,
        trend=trend,
        trend_quarters_shown=len(trend),
        trend_quarters_total=TREND_QUARTERS,
        top_holders=top_holders,
        note=note,
    )
