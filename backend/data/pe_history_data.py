"""P/E history chart (Ratios tab): the ticker's own trailing P/E beside FMP's sector / industry average P/E, last
1 year only (docs/specs/sector-industry-pe.md, "Phase 2"). Cache-only: no FMP call, no write.

Ticker line = daily close (cached daily bars through the last completed session; split-adjusted, like the cached
statements' EPS) / TTM EPS, where TTM EPS is the sum of 4 consecutive quarterly `epsDiluted` and applies from the 4th
quarter's `filingDate` (fallback: period end + 45 days), so no day uses an EPS that was not yet public. A day with TTM
EPS <= 0 is dropped (same positive-EPS rule as the header P/E). A window of quarters with a gap, or holding a Q4 row
that duplicates its fiscal year's annual EPS (helpers/ttm.py::is_quarter_content_duplicate_of_annual), yields no value
from its filing date until the next valid window (it is not corrected).

Not like for like with the header P/E (`netIncomePerShareTTM`, live price) and not with FMP's sector / industry
average (unknown averaging): the UI says so.

`engine` is a module-level reference so tests can monkeypatch it."""

import json
from datetime import date, timedelta

import pandas as pd
from sqlmodel import Session, select

from clients.shared_bars_cache import read_cached_completed_daily_bars
from core.db import engine
from core.models import FundamentalsCache
from core.schemas import PeHistoryLatest, PeHistoryOut, PeHistoryPoint
from data.sector_industry_pe_data import EXCHANGES, INDUSTRY, LABEL, SECTOR, get_series, window_start
from helpers.ttm import is_quarter_content_duplicate_of_annual

CHART_WINDOW_YEARS = 1
# Bars are read a little wider than the window so the first day of the window is never short of a bar.
_BAR_LOOKBACK_DAYS = 366 + 10
# Neighbouring quarters are 91 days apart; outside this range a quarter is missing or duplicated.
_MIN_QUARTER_GAP_DAYS = 60
_MAX_QUARTER_GAP_DAYS = 135
_FILING_LAG_FALLBACK_DAYS = 45
# A sector / industry value is carried onto a bar date from at most this many calendar days earlier.
_OVERLAY_TOLERANCE = pd.Timedelta(days=5)

STOCK_OK, STOCK_ADR, STOCK_NO_EPS, STOCK_NO_PRICES = "ok", "adr", "no_eps", "no_prices"

NOTE_ETF = "ETFs and funds have no P/E history."
NOTE_EXCHANGE = "No sector or industry P/E is stored for this listing exchange (NASDAQ, NYSE and AMEX only)."
NOTE_NO_PROFILE = "No cached profile for this ticker yet, so the P/E history is unavailable."


def _parse_day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def ttm_eps_steps(quarters: list[dict], annual: list[dict]) -> list[tuple[date, float | None]]:
    """[(available_from, ttm_eps_or_None)] ascending. Each step holds from its date until the next step; None means
    no usable value from that date (broken window), so an older value is never carried across it."""
    rows: list[tuple[date, date, float, dict]] = []
    for row in quarters:
        end, eps = _parse_day(row.get("date")), row.get("epsDiluted")
        if end is None or isinstance(eps, bool) or not isinstance(eps, (int, float)) or eps != eps:
            continue
        filed = _parse_day(row.get("filingDate")) or end + timedelta(days=_FILING_LAG_FALLBACK_DAYS)
        rows.append((end, max(filed, end), float(eps), row))
    rows.sort(key=lambda r: r[0])
    steps: list[tuple[date, float | None]] = []
    latest_available = None
    for i in range(3, len(rows)):
        window = rows[i - 3 : i + 1]
        gaps = [(window[j + 1][0] - window[j][0]).days for j in range(3)]
        valid = all(_MIN_QUARTER_GAP_DAYS <= g <= _MAX_QUARTER_GAP_DAYS for g in gaps)
        if valid:
            valid = not any(
                is_quarter_content_duplicate_of_annual(annual, [w[3]], "epsDiluted") for w in window
            )
        available = rows[i][1]
        if latest_available is not None and available < latest_available:
            available = latest_available  # filings can arrive out of order; availability never moves backwards
        latest_available = available
        steps.append((available, round(sum(w[2] for w in window), 6) if valid else None))
    return steps


def ticker_pe_series(closes: pd.Series, steps: list[tuple[date, float | None]]) -> pd.Series:
    """Daily P/E (close / TTM EPS) over `closes` (date-indexed, ascending). Days before the first step, with no EPS
    in force or with EPS <= 0 are absent. Rounded to 2 places."""
    if closes.empty or not steps:
        return pd.Series(dtype=float)
    eps = pd.DataFrame({"available": pd.to_datetime([s[0] for s in steps]).astype("datetime64[ns]"), "eps": [s[1] for s in steps]})
    # merge_asof keeps the latest step on/before each bar date, including a None step (a broken window).
    left = pd.DataFrame({"date": closes.index.astype("datetime64[ns]"), "close": closes.to_numpy()})
    merged = pd.merge_asof(left, eps.astype({"eps": "float64"}), left_on="date", right_on="available")
    ok = merged["eps"].notna() & (merged["eps"] > 0)
    pe = (merged["close"] / merged["eps"]).where(ok).round(2)
    return pd.Series(pe.to_numpy(), index=closes.index).dropna()


def _cached(ticker: str) -> dict[tuple[str, str], list[dict]]:
    with Session(engine) as session:
        rows = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == ticker,
                FundamentalsCache.statement_type.in_(["profile", "income_statement"]),
            )
        ).all()
    out: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        try:
            data = json.loads(row.raw_json)
        except ValueError:
            continue
        out[(row.statement_type, row.period)] = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    return out


def _series_frame(rows: list[tuple[date, float]]) -> pd.Series:
    """A stored sector / industry series with `pe <= 0` (FMP's "no value" day) turned into NaN. The day stays in the
    series so the as-of carry below lands on the gap instead of bridging it with the day before."""
    if not rows:
        return pd.Series(dtype=float)
    values = [pe if pe > 0 else float("nan") for _, pe in rows]
    return pd.Series(values, index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in rows]))


def _carry(base: pd.DatetimeIndex, series: pd.Series) -> pd.Series:
    """`series` as of each date in `base` (last value on/before, within the tolerance), NaN where none."""
    if series.empty or len(base) == 0:
        return pd.Series(float("nan"), index=base)
    left = pd.DataFrame({"date": base.astype("datetime64[ns]")})
    right = pd.DataFrame({"date": series.index.astype("datetime64[ns]"), "v": series.to_numpy()})
    merged = pd.merge_asof(left, right, on="date", tolerance=_OVERLAY_TOLERANCE)
    return pd.Series(merged["v"].to_numpy(), index=base)


def _latest(series: pd.Series) -> PeHistoryLatest | None:
    s = series.dropna()
    if s.empty:
        return None
    return PeHistoryLatest(value=round(float(s.iloc[-1]), 2), date=s.index[-1].date().isoformat())


def _empty(ticker: str, status: str, note: str, **extra) -> PeHistoryOut:
    return PeHistoryOut(ticker=ticker, status=status, note=note, label=LABEL, **extra)


def get_pe_history(ticker: str) -> PeHistoryOut:
    cached = _cached(ticker)
    profiles = cached.get(("profile", "latest")) or next((v for (t, _), v in cached.items() if t == "profile" and v), [])
    profile = profiles[0] if profiles else {}
    if not profile:
        return _empty(ticker, "no_profile", NOTE_NO_PROFILE)
    if profile.get("isEtf") or profile.get("isFund"):
        return _empty(ticker, "etf", NOTE_ETF)
    exchange, sector, industry = profile.get("exchange"), profile.get("sector"), profile.get("industry")
    if exchange not in EXCHANGES:
        return _empty(ticker, "unsupported_exchange", NOTE_EXCHANGE, exchange=exchange, sector=sector, industry=industry)

    start = window_start(years=CHART_WINDOW_YEARS)
    sector_series = _series_frame(get_series(SECTOR, sector, exchange, years=CHART_WINDOW_YEARS)) if sector else pd.Series(dtype=float)
    industry_series = (
        _series_frame(get_series(INDUSTRY, industry, exchange, years=CHART_WINDOW_YEARS)) if industry else pd.Series(dtype=float)
    )
    industry_fallback = not industry_series.notna().any() and sector_series.notna().any()

    quarters = cached.get(("income_statement", "quarterly"), [])
    annual = cached.get(("income_statement", "annual"), [])
    bars = read_cached_completed_daily_bars(ticker, _BAR_LOOKBACK_DAYS)
    closes = bars["close"].dropna() if len(bars) else pd.Series(dtype=float)
    # An empty frame has a RangeIndex; normalise so the date slice and joins below always see a DatetimeIndex.
    closes = closes.iloc[0:0].set_axis(pd.DatetimeIndex([])) if closes.empty else closes[closes.index >= pd.Timestamp(start)]

    reported = quarters[0].get("reportedCurrency") if quarters else None
    quote_currency = profile.get("currency")
    stock = pd.Series(dtype=float)
    if reported and quote_currency and reported != quote_currency:
        stock_status = STOCK_ADR
    elif closes.empty:
        stock_status = STOCK_NO_PRICES
    else:
        stock = ticker_pe_series(closes, ttm_eps_steps(quarters, annual))
        stock_status = STOCK_OK if not stock.empty else STOCK_NO_EPS

    # Calendar: the bar dates when the ticker has bars, else the stored sector / industry dates.
    if not closes.empty:
        base = closes.index
    else:
        union = sector_series.index.union(industry_series.index)
        base = union[union >= pd.Timestamp(start)]
    sector_line = _carry(base, sector_series)
    industry_line = _carry(base, industry_series)
    stock_line = stock.reindex(base)

    frame = pd.DataFrame({"stock": stock_line, "sector": sector_line, "industry": industry_line}, index=base)
    frame = frame.dropna(how="all")
    points = [
        PeHistoryPoint(
            date=idx.date().isoformat(),
            stock=None if pd.isna(row.stock) else float(row.stock),
            sector=None if pd.isna(row.sector) else round(float(row.sector), 2),
            industry=None if pd.isna(row.industry) else round(float(row.industry), 2),
        )
        for idx, row in frame.iterrows()
    ]
    return PeHistoryOut(
        ticker=ticker,
        status="ok",
        label=LABEL,
        window_start=start.isoformat(),
        exchange=exchange,
        sector=sector,
        industry=industry,
        stock_status=stock_status,
        stock_starts=stock.index[0].date().isoformat() if not stock.empty else None,
        sector_available=bool(sector_series.notna().any()),
        industry_available=bool(industry_series.notna().any()),
        industry_fallback=industry_fallback,
        points=points,
        latest_stock=_latest(stock_line),
        latest_sector=_latest(sector_line),
        latest_industry=_latest(industry_line),
    )
