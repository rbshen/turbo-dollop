"""ETF page data: the Overview tab (FMP `/etf/info` only) and "is this ticker a known ETF" lookups.

`/etf/info` is the one ETF endpoint the app calls (data group `etf_info`, cache key
`(ticker, "etf_info", "latest")` in FundamentalsCache, TTL `Settings.etf_info_staleness_days`).
No holdings, country-weight or asset-exposure endpoint is used; the sector weights come from the
`sectorsList` inside the same response.

`engine` is a module-level reference so tests can monkeypatch it (the per-module engine-isolation
convention)."""

import logging
from collections.abc import Iterable
from datetime import datetime

import httpx
from sqlalchemy import or_
from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from core.cache import get_or_fetch
from core.config import settings
from core.db import engine
from core.models import FundamentalsCache, TickerScore
from core.schemas import EtfOverviewOut, EtfSectorWeightOut
from core.tickers import normalize_ticker

logger = logging.getLogger(__name__)

ETF_INFO_STATEMENT_TYPE = "etf_info"

# FMP's placeholder sector for the part of a fund that is not stocks. A non-equity fund (bond,
# commodity) reports ONLY this, at 100% -- meaningless as a "sector weight".
_CASH_AND_OTHERS = "cash & others"


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def _positive(value) -> float | None:
    """A fact FMP reports as 0 for "unknown" (GLD's holdingsCount, a missing NAV) is omitted, not shown as 0."""
    number = _number(value)
    return number if number is not None and number > 0 else None


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _sector_weights(asset_class: str | None, sectors_list) -> list[EtfSectorWeightOut]:
    """Largest first; empty for a non-equity fund or when the list is only "Cash & Others"."""
    if asset_class is not None and asset_class.lower() != "equity":
        return []
    entries: list[EtfSectorWeightOut] = []
    for item in sectors_list if isinstance(sectors_list, list) else []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("industry"))
        weight = _number(item.get("exposure"))
        if name is None or weight is None or weight <= 0:
            continue
        entries.append(EtfSectorWeightOut(sector=name, weight=weight))
    if all(entry.sector.lower() == _CASH_AND_OTHERS for entry in entries):
        return []
    return sorted(entries, key=lambda entry: entry.weight, reverse=True)


def _overview_from_payload(ticker: str, payload: dict | list, fetched_at: datetime | None) -> EtfOverviewOut:
    row = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else None
    if row is None:
        return EtfOverviewOut(ticker=ticker, status="no_data")
    asset_class = _text(row.get("assetClass"))
    holdings_count = _positive(row.get("holdingsCount"))
    return EtfOverviewOut(
        ticker=ticker,
        status="ok",
        name=_text(row.get("name")),
        issuer=_text(row.get("etfCompany")),
        asset_class=asset_class,
        expense_ratio=_number(row.get("expenseRatio")),
        assets_under_management=_positive(row.get("assetsUnderManagement")),
        holdings_count=int(holdings_count) if holdings_count is not None else None,
        nav=_positive(row.get("nav")),
        nav_currency=_text(row.get("navCurrency")),
        avg_volume=_positive(row.get("avgVolume")),
        inception_date=_text(row.get("inceptionDate")),
        domicile=_text(row.get("domicile")),
        description=_text(row.get("description")),
        website=_text(row.get("website")),
        sector_weights=_sector_weights(asset_class, row.get("sectorsList")),
        updated_at=_text(row.get("updatedAt")),
        fetched_at=fetched_at,
    )


def _cached_row(session: Session, ticker: str) -> FundamentalsCache | None:
    return session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker,
            FundamentalsCache.statement_type == ETF_INFO_STATEMENT_TYPE,
            FundamentalsCache.period == "latest",
        )
    ).first()


async def get_etf_overview(ticker: str) -> EtfOverviewOut:
    """Never raises for an FMP problem: the group being off, or a failed fetch, with nothing cached
    comes back as status "unavailable" (the Overview shows its own state; the Technical and Chart
    tabs do not depend on this). A failed refetch with a stale row cached serves the stale row."""
    ticker = normalize_ticker(ticker)
    failed = False
    with Session(engine) as session:
        try:
            payload = await get_or_fetch(
                session,
                ticker,
                ETF_INFO_STATEMENT_TYPE,
                "latest",
                lambda: fmp_client.get_etf_info(ticker),
                settings.etf_info_staleness_days,
            )
        except httpx.HTTPError as exc:
            logger.warning("FMP fetch failed for etf_info %s: %s", ticker, exc)
            failed = True
            payload = await get_or_fetch(
                session, ticker, ETF_INFO_STATEMENT_TYPE, "latest", lambda: fmp_client.get_etf_info(ticker),
                settings.etf_info_staleness_days, cache_only=True,
            )
        row = _cached_row(session, ticker) if payload is not None else None

    if payload is None:
        # get_or_fetch returns None without calling FMP only when the group is not live (cache-only
        # semantics) and nothing is cached; a failed live fetch is the other way to get here.
        return EtfOverviewOut(ticker=ticker, status="unavailable", reason="fetch_failed" if failed else "group_off")
    return _overview_from_payload(ticker, payload, row.fetched_at if row else None)


# ---------------------------------------------------------------------------
# "Is this a known ETF?" -- local knowledge only, never an FMP call
# ---------------------------------------------------------------------------

# FundamentalsCache stores json.dumps(...) of the profile, so a boolean serialises as `"isEtf": true`.
_PROFILE_ETF_MARKERS = ('%"isEtf": true%', '%"isFund": true%')


def known_etf_tickers(session: Session, tickers: Iterable[str] | None = None) -> set[str]:
    """Tickers (among `tickers`, or every one when None) the app already knows are an ETF or fund:
    a TickerScore row with is_etf, or a cached FMP profile with isEtf/isFund. Same `isEtf or
    isFund` rule as everywhere else. A ticker that was never opened, scored or watchlisted is
    simply unknown (not an ETF)."""
    wanted = {normalize_ticker(t) for t in tickers} if tickers is not None else None
    if wanted is not None and not wanted:
        return set()

    score_query = select(TickerScore.ticker).where(TickerScore.is_etf == True)  # noqa: E712 -- SQL comparison
    profile_query = select(FundamentalsCache.ticker).where(
        FundamentalsCache.statement_type == "profile",
        or_(*[FundamentalsCache.raw_json.like(marker) for marker in _PROFILE_ETF_MARKERS]),
    )
    if wanted is not None:
        score_query = score_query.where(TickerScore.ticker.in_(wanted))
        profile_query = profile_query.where(FundamentalsCache.ticker.in_(wanted))
    return set(session.exec(score_query).all()) | set(session.exec(profile_query).all())


def is_known_etf(session: Session, ticker: str) -> bool:
    return normalize_ticker(ticker) in known_etf_tickers(session, [ticker])
