"""ETF page data: the Overview tab (FMP `/etf/info`, plus the cache-only "Trading data" block) and "is this
ticker a known ETF" lookups.

`/etf/info` is the one ETF endpoint the app calls (data group `etf_info`, cache key
`(ticker, "etf_info", "latest")` in FundamentalsCache, TTL `Settings.etf_info_staleness_days`).
No holdings, country-weight or asset-exposure endpoint is used; the sector weights come from the
`sectorsList` inside the same response.

`engine` is a module-level reference so tests can monkeypatch it (the per-module engine-isolation
convention)."""

import logging
from collections.abc import Iterable
from datetime import date, datetime

import httpx
import pandas as pd
from sqlalchemy import or_
from sqlmodel import Session, select

from clients.fmp_client import fmp_client
from clients.shared_bars_cache import _most_recent_completed_trading_date, read_cached_completed_daily_bars
from core.cache import get_or_fetch
from core.config import settings
from core.db import engine
from core.models import FundamentalsCache, TickerScore
from core.schemas import EtfOverviewOut, EtfSectorWeightOut, EtfTradingDataOut
from core.tickers import normalize_ticker
from helpers.first import _first
from scoring.etf_returns import MAX_STALE_DAYS, compute_window_returns

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



# ---------------------------------------------------------------------------
# Trading data block (cache-only: no FMP call, no new table)
# ---------------------------------------------------------------------------

# Calendar days of cached daily bars read for the block: the 1Y window needs a bar on/before
# (anchor - 1 year), plus a margin for a weekend/holiday at that boundary.
TRADING_DATA_BAR_LOOKBACK_DAYS = 400


def _nonzero(value: float | None, digits: int | None = None) -> float | None:
    """None for a missing, non-finite or zero value. `digits` rounds first, so a return that would print
    as 0.00% is omitted like a true zero."""
    number = _number(value)
    if number is None or number != number:  # NaN
        return None
    if digits is not None:
        number = round(number, digits)
    return number if number != 0 else None


def _bar_trading_stats(frame: pd.DataFrame, completed: date) -> dict:
    """1M / YTD / 1Y price returns and the volume averages from cached daily bars. Returns are the shared
    Sector Heatmap math (scoring/etf_returns.py::compute_window_returns): calendar-offset base, last close
    on/before it, a window with no bar that far back (a young fund, a shallow cache) is None, and the
    whole set is None when the newest bar is more than MAX_STALE_DAYS older than the last completed session."""
    stats: dict = {}
    if frame is None or frame.empty:
        return stats
    close = frame["close"].dropna()
    if close.empty:
        return stats
    anchor = close.index.max().normalize()
    if (completed - anchor.date()).days > MAX_STALE_DAYS:
        return stats
    by_window = {r.window: r.return_pct for r in compute_window_returns(close, anchor)}
    stats.update(
        perf_1m=_nonzero(by_window.get("1m"), 2),
        perf_ytd=_nonzero(by_window.get("ytd"), 2),
        perf_1y=_nonzero(by_window.get("1y"), 2),
        perf_as_of=anchor.date(),
    )
    recent = frame[frame.index >= anchor - pd.Timedelta(days=30)]
    stats["avg_volume_30d"] = _nonzero(recent["volume"].mean()) if not recent.empty else None
    last_20 = frame.tail(20)
    stats["avg_dollar_volume_20d"] = _nonzero((last_20["close"] * last_20["volume"]).mean())
    stats["last_close"] = float(close.iloc[-1])
    return stats


async def _cache_only_row(ticker: str, statement_type: str, fetch_fn) -> dict:
    with Session(engine) as session:
        payload = await get_or_fetch(
            session, ticker, statement_type, "latest", fetch_fn, settings.profile_staleness_days, cache_only=True
        )
    return _first(payload) if payload is not None else {}


async def _trading_data(ticker: str, asset_class: str | None) -> EtfTradingDataOut | None:
    """The Overview's Trading data block, or None when every value is unavailable. Reads only what is
    already cached (cache_only reads of the profile and quote rows, the shared daily bars), so it adds no
    FMP call and never blocks on one. Rules (docs/specs/etf-page.md): a zero/None value is omitted; beta
    only for an equity fund; yield = profile `lastDividend` / current price; profile `marketCap` is never
    used (AUM from /etf/info stays the only size figure)."""
    profile = await _cache_only_row(ticker, "profile", lambda: fmp_client.get_profile(ticker))
    quote = await _cache_only_row(ticker, "quote", lambda: fmp_client.get_quote(ticker))
    completed = _most_recent_completed_trading_date()
    stats = _bar_trading_stats(read_cached_completed_daily_bars(ticker, TRADING_DATA_BAR_LOOKBACK_DAYS), completed)

    low, high = _positive(quote.get("yearLow")), _positive(quote.get("yearHigh"))
    price = _positive(quote.get("price")) or stats.get("last_close")
    per_share = _positive(profile.get("lastDividend"))
    is_equity = asset_class is not None and asset_class.lower() == "equity"

    data = EtfTradingDataOut(
        perf_1m=stats.get("perf_1m"),
        perf_ytd=stats.get("perf_ytd"),
        perf_1y=stats.get("perf_1y"),
        perf_as_of=stats.get("perf_as_of"),
        week52_low=low if low is not None and high is not None else None,
        week52_high=high if low is not None and high is not None else None,
        avg_volume_30d=stats.get("avg_volume_30d"),
        avg_dollar_volume_20d=stats.get("avg_dollar_volume_20d"),
        distribution_ttm_per_share=per_share if price is not None else None,
        distribution_ttm_yield_pct=_nonzero(per_share / price * 100, 2) if per_share is not None and price is not None else None,
        beta=_nonzero(profile.get("beta"), 2) if is_equity else None,
    )
    values = data.model_dump(exclude={"perf_as_of"})
    return data if any(v is not None for v in values.values()) else None


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
    overview = _overview_from_payload(ticker, payload, row.fetched_at if row else None)
    if overview.status == "ok":
        overview.trading_data = await _trading_data(ticker, overview.asset_class)
    return overview


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
