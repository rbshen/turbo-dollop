"""Assembles the "Why might it be stuck?" card from cached data only (docs/specs/stuck-check.md): no FMP call, no write, feeds nothing.

Fundamental rows read the cleaned cached statements (`helpers/statement_view.build_statement_view`, completed fiscal years), the
price rows read the stored `TickerScore` values (never recomputed), and relative strength reads cached daily bars. The labelling
rules are scoring/stuck_check.py; thresholds come from `load_stuck_settings` with the code defaults as the fallback.
"""

import json
import time
from datetime import date

import pandas as pd
from sqlmodel import Session, select

from clients.shared_bars_cache import read_cached_daily_bars_batch
from core.db import engine
from core.models import FundamentalsCache, TickerScore
from core.schemas import StuckCheckOut, StuckFigureOut, StuckRowOut
from core.tickers import normalize_ticker
from data.market_breadth_data import SECTOR_TO_ETF
from data.stuck_check_settings import load_stuck_settings
from data.tracked_universe import load_tracked_universe
from helpers.statement_view import build_statement_view, read_cached_inputs
from scoring.stuck_check import (
    RELATIVE_STRENGTH_WINDOWS,
    SUBTITLE,
    FiscalYear,
    StoredPriceValues,
    StuckRow,
    StuckSettings,
    evaluate_fundamental_rows,
    footer_line,
    price_context_row,
    relative_strength_row,
    revenue_cagr_pct,
)

BARS_LOOKBACK_DAYS = 430  # a 12-month return needs a base bar a year back, plus slack for a holiday
SECTOR_CONTEXT_TTL_SECONDS = 600.0
SPY = "SPY"


# --- cached reads ------------------------------------------------------------------------------------------------------------


def _cached_rows(session: Session, ticker: str, statement_type: str, period: str) -> list[dict]:
    row = session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker,
            FundamentalsCache.statement_type == statement_type,
            FundamentalsCache.period == period,
        )
    ).first()
    if row is None:
        return []
    try:
        data = json.loads(row.raw_json)
    except ValueError:
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


def build_fiscal_years(income: list[dict], cash_flow: list[dict], key_metrics: list[dict]) -> list[FiscalYear]:
    """Chronological (oldest first) fiscal years from most-recent-first annual rows, cash flow and key metrics joined on fiscalYear."""
    cash_by_year = {r.get("fiscalYear"): r for r in cash_flow}
    metrics_by_year = {r.get("fiscalYear"): r for r in key_metrics}
    years = []
    for row in reversed(income):
        fy = row.get("fiscalYear") or (row.get("date") or "")[:4]
        cf = cash_by_year.get(fy, {})
        km = metrics_by_year.get(fy, {})
        cfo, capex = _num(cf.get("netCashProvidedByOperatingActivities")), _num(cf.get("capitalExpenditure"))
        repurchased = _num(cf.get("commonStockRepurchased"))
        net_issuance = _num(cf.get("netCommonStockIssuance"))
        dividends = _num(cf.get("netDividendsPaid"))
        if dividends is None:
            dividends = _num(cf.get("commonDividendsPaid"))
        shares = _num(row.get("weightedAverageShsOutDil")) or _num(row.get("weightedAverageShsOut"))
        roic = _num(km.get("returnOnInvestedCapital"))
        years.append(
            FiscalYear(
                fiscal_year=str(fy),
                period_end=_parse_date(row.get("date")),
                revenue=_num(row.get("revenue")),
                net_income=_num(row.get("netIncome")),
                operating_income=_num(row.get("operatingIncome")),
                gross_profit=_num(row.get("grossProfit")),
                fcf=cfo + capex if cfo is not None and capex is not None else None,
                sbc=_num(cf.get("stockBasedCompensation")),
                buybacks=abs(repurchased) if repurchased is not None else None,
                net_buybacks=-net_issuance if net_issuance is not None else None,
                dividends=abs(dividends) if dividends is not None else None,
                diluted_shares=shares,
                roic_pct=roic * 100 if roic is not None else None,
            )
        )
    return years


# --- sector context (peers) --------------------------------------------------------------------------------------------------


class _SectorContext:
    def __init__(self, cagrs: list[float], market_caps: dict[str, float]):
        self.cagrs = cagrs
        self.market_caps = market_caps


_sector_cache: dict[tuple[int, str], tuple[float, _SectorContext]] = {}


def invalidate_sector_cache() -> None:
    _sector_cache.clear()


def _revenue_cagr_of_cached(session: Session, ticker: str) -> float | None:
    rows = _cached_rows(session, ticker, "income_statement", "annual")
    return revenue_cagr_pct(build_fiscal_years(rows, [], []))


def sector_context(session: Session, sector: str) -> _SectorContext:
    """Tracked stocks in `sector`: their 5-year revenue CAGRs (from cached annual income statements) and market caps. Held for a few
    minutes in process: it is read by every card open and changes only with the nightly fetch."""
    key = (id(engine), sector)
    now = time.monotonic()
    hit = _sector_cache.get(key)
    if hit and now - hit[0] < SECTOR_CONTEXT_TTL_SECONDS:
        return hit[1]
    tracked = set(load_tracked_universe(session))
    members = session.exec(select(TickerScore).where(TickerScore.sector == sector)).all()
    cagrs: list[float] = []
    caps: dict[str, float] = {}
    for member in members:
        if member.ticker not in tracked or member.is_etf:
            continue
        if member.market_cap and (member.quote_currency in (None, "USD")):
            caps[member.ticker] = member.market_cap
        cagr = _revenue_cagr_of_cached(session, member.ticker)
        if cagr is not None:
            cagrs.append(cagr)
    context = _SectorContext(cagrs, caps)
    _sector_cache[key] = (now, context)
    return context


# --- relative strength -------------------------------------------------------------------------------------------------------


def trailing_returns_pct(close: pd.Series, end: pd.Timestamp) -> dict[int, float | None]:
    """Total return in percent over 1/3/6/12 calendar months ending at the last bar on or before `end`; None when the cached history
    does not reach back far enough for a window."""
    close = close[close.index <= end].dropna()
    result: dict[int, float | None] = {m: None for m in RELATIVE_STRENGTH_WINDOWS}
    if close.empty or close.iloc[-1] <= 0:
        return result
    last_date, last = close.index[-1], close.iloc[-1]
    for months in RELATIVE_STRENGTH_WINDOWS:
        anchor = last_date - pd.DateOffset(months=months)
        if close.index[0] > anchor:
            continue
        base = close[close.index <= anchor]
        if not base.empty and base.iloc[-1] > 0:
            result[months] = (last / base.iloc[-1] - 1) * 100
    return result


def _relative_strength(ticker: str, sector: str | None, band_pp: float, weight_pct: float | None) -> StuckRow:
    etf = SECTOR_TO_ETF.get(sector or "")
    if etf is None:
        return relative_strength_row({}, None, {}, None, band_pp)
    frames = read_cached_daily_bars_batch([ticker, etf, SPY], BARS_LOOKBACK_DAYS)
    closes = {name: frames[name]["close"] for name in (ticker, etf, SPY) if name in frames and not frames[name].empty}
    if ticker not in closes:
        return relative_strength_row({m: None for m in RELATIVE_STRENGTH_WINDOWS}, {}, {}, etf, band_pp)
    # One common end date, so a stale benchmark bar cannot shift a window.
    end = min(series.index[-1] for series in closes.values())
    returns = {name: trailing_returns_pct(series, end) for name, series in closes.items()}
    empty = {m: None for m in RELATIVE_STRENGTH_WINDOWS}
    return relative_strength_row(returns[ticker], returns.get(etf, empty), returns.get(SPY, empty), etf, band_pp, weight_pct)


# --- the card ----------------------------------------------------------------------------------------------------------------


def _row_out(row: StuckRow) -> StuckRowOut:
    return StuckRowOut(
        key=row.key,
        number=row.number,
        title=row.title,
        status=row.status,
        reason=row.reason,
        figures=[StuckFigureOut(**vars(f)) for f in row.figures],
        notes=row.notes,
    )


def get_stuck_check_data(ticker: str, settings: StuckSettings | None = None) -> StuckCheckOut:
    """Cache only: reads `FundamentalsCache`, `TickerScore`, `SharedBarsCache` and never fetches or writes."""
    ticker = normalize_ticker(ticker)
    settings = settings if settings is not None else load_stuck_settings(engine)
    with Session(engine) as session:
        score = session.get(TickerScore, ticker)
        profile_rows = _cached_rows(session, ticker, "profile", "latest")
        profile = profile_rows[0] if profile_rows else {}
        if profile.get("isEtf") or profile.get("isFund") or (score is not None and score.is_etf):
            return StuckCheckOut(ticker=ticker, applicable=False, not_applicable_reason="Stocks only", has_data=False)

        raw, _earnings, company_type = read_cached_inputs(session, ticker)
        view = build_statement_view(raw, company_type, use_balance_sheet=False)
        years = build_fiscal_years(view.income_annual, view.cash_flow_annual, _cached_rows(session, ticker, "key_metrics", "annual"))
        sector = profile.get("sector") or (score.sector if score else None)
        context = sector_context(session, sector) if sector else _SectorContext([], {})

    stored = (
        StoredPriceValues(
            overall_verdict=score.overall_verdict,
            valuation_verdict=score.valuation_verdict,
            weinstein_stage=score.weinstein_stage,
            weinstein_since=score.weinstein_stage_since_date,
            weinstein_since_is_lower_bound=score.weinstein_stage_since_is_lower_bound,
            perf_5y_vs_spy_status=score.perf_5y_vs_spy_status,
            perf_5y_vs_spy_pct=score.perf_5y_vs_spy_pct,
        )
        if score is not None
        else None
    )
    if not years:
        return StuckCheckOut(ticker=ticker, has_data=False, company_type=company_type, rows=[_row_out(price_context_row(stored))])

    total_cap = sum(context.market_caps.values())
    own_cap = context.market_caps.get(ticker) or (score.market_cap if score else None)
    weight_pct = own_cap / total_cap * 100 if own_cap and total_cap else None
    ipo_date = _parse_date(profile.get("ipoDate"))

    rows = evaluate_fundamental_rows(years, company_type, ticker, ipo_date, settings, context.cagrs)
    footer = footer_line(rows)
    rows.append(price_context_row(stored))
    rows.append(_relative_strength(ticker, sector, settings.sector_band_pp, weight_pct))
    rows.sort(key=lambda r: r.number)
    return StuckCheckOut(
        ticker=ticker, subtitle=SUBTITLE, company_type=company_type, rows=[_row_out(r) for r in rows], footer=footer
    )
