"""Orchestration layer for the ticker-page Chart tab -- OHLC candles plus
EMA21, SMA50/200, Bollinger(20,2, EMA basis), Full Stochastic(5,3,3), and
RSI(14), across four fixed views (D/6M, D/1Y, D/2Y, W/4Y). See CLAUDE.md's
Chart tab investigation notes for the full design history; the two
decisions this module embodies:

1. Fully ON-DEMAND -- no new nightly cron job, no new precomputed table
   (confirmed fast enough for a page load in the latency investigation:
   median ~0.14s combined daily+weekly fetch, worst case ~0.56s). Every
   request computes fresh from whichever bar source is currently active.
2. On the FMP branch, this still goes through the app's ordinary
   get_or_fetch-backed FundamentalsCache (via daily_price_sources.py,
   reused as-is) -- "on-demand" means no NEW persistence layer was built for
   this feature, not that FMP's own standing cache is bypassed (every other
   FMP call in this app goes through it; skipping it here would burn FMP
   quota on every Chart tab view for a popular ticker). On the Yahoo branch,
   clients/yahoo_cache.py's YahooPriceCache table is deliberately NOT used
   -- its staleness check is coverage-blind (a cache row freshened by the
   2y/4y nightly jobs reads as "fresh" even when this feature needs 8y of
   history), so this calls clients/yahoo_client.py directly instead, with no
   persistence at all.
"""

from datetime import date, datetime

import pandas as pd

from analysis.entry_signal.indicators import BB_LENGTH, BB_STD, compute_rsi
from analysis.trend_structure.stochastic import compute_stochastic
from analysis.trend_structure.weinstein import resample_to_weekly
from clients.daily_price_sources import FMPDailyBarSource
from clients.yahoo_client import yahoo_client
from core.config import settings
from core.schemas import (
    ChartBarOut,
    ChartBollingerPointOut,
    ChartLinePointOut,
    ChartMarkerOut,
    ChartOut,
    ChartStochasticPointOut,
    ChartZoneOut,
    LiquidityZoneOut,
)
from core.tickers import normalize_ticker
from data.entry_signal_data import get_entry_signal_data
from data.liquidity_zone_data import get_liquidity_zone_data

_EMPTY_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# Per-range fetch/visible-window configuration. `fmp_lookback_years` and
# `yahoo_period` both over-fetch slightly relative to the bare
# warm-up-plus-visible-window math (see CLAUDE.md) -- yfinance's period enum
# has no exact "2.8y"/"3y" value, and a little extra fetched history costs
# nothing (indicators are computed on the full series and sliced afterward
# regardless), so both are snapped to the nearest covering value rather than
# fetched at exact precision.
RANGE_CONFIG: dict[str, dict] = {
    # Same fmp_lookback_years/yahoo_period as D_1Y -- both already comfortably
    # cover the ~1.3y actually needed (182 visible days + ~200-bar SMA200
    # warm-up + margin); only visible_days is halved.
    "D_6M": {"timeframe": "daily", "fmp_lookback_years": 2, "yahoo_period": "2y", "visible_days": 365 // 2},
    "D_1Y": {"timeframe": "daily", "fmp_lookback_years": 2, "yahoo_period": "2y", "visible_days": 365},
    "D_2Y": {"timeframe": "daily", "fmp_lookback_years": 3, "yahoo_period": "5y", "visible_days": 365 * 2},
    # FMP has no weekly endpoint (confirmed 404 on /historical-chart/1week)
    # -- the FMP branch always fetches DAILY here and resamples locally.
    # The Yahoo branch fetches interval="1wk" directly instead (confirmed
    # bit-identical to resampling, and faster/simpler, in the latency
    # investigation) -- see _fetch_bars below.
    "W_4Y": {"timeframe": "weekly", "fmp_lookback_years": 8, "yahoo_period": "10y", "visible_days": 365 * 4},
}


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=_EMPTY_OHLCV_COLUMNS)


async def _fetch_bars(ticker: str, range_key: str) -> tuple[pd.DataFrame, str]:
    """Returns (lowercase-column OHLCV DataFrame, "fmp"|"yahoo"). Empty
    DataFrame (never None/raised) for a bad/delisted ticker or a fetch that
    returned nothing -- get_chart_data below is the single place that turns
    that into chart_available=False."""
    cfg = RANGE_CONFIG[range_key]

    if settings.fmp_enabled:
        # Reused directly (not clients.daily_price_sources.get_daily_bar_source(),
        # which would also hand back YahooDailyBarSource on the disabled
        # branch -- that class persists into YahooPriceCache, exactly the
        # table this feature avoids; see module docstring) since only the
        # FMP half of that module's dual-source pattern applies here.
        result = await FMPDailyBarSource().get_daily_bars([ticker], cfg["fmp_lookback_years"])
        df = result.get(ticker, _empty_ohlcv())
        if cfg["timeframe"] == "weekly" and not df.empty:
            df = resample_to_weekly(df)
        return df, "fmp"

    interval = "1wk" if cfg["timeframe"] == "weekly" else "1d"
    result = await yahoo_client.get_history([ticker], period=cfg["yahoo_period"], interval=interval)
    raw = result.get(ticker)
    if raw is None or raw.empty:
        return _empty_ohlcv(), "yahoo"
    # yfinance's own native Open/High/Low/Close/Volume casing -> this
    # module's (and resample_to_weekly's) lowercase convention.
    return raw.rename(columns=str.lower)[_EMPTY_OHLCV_COLUMNS], "yahoo"


def _fmt(ts: pd.Timestamp | date) -> str:
    return ts.strftime("%Y-%m-%d")


def _line_points(series: pd.Series, mask: pd.Series) -> list[ChartLinePointOut]:
    visible = series[mask].dropna()
    return [ChartLinePointOut(time=_fmt(idx), value=float(v)) for idx, v in visible.items()]


def _bollinger_points(upper: pd.Series, middle: pd.Series, lower: pd.Series, mask: pd.Series) -> list[ChartBollingerPointOut]:
    out = []
    for idx in upper.index[mask]:
        u, m, l = upper.loc[idx], middle.loc[idx], lower.loc[idx]
        if pd.isna(u) or pd.isna(m) or pd.isna(l):
            continue
        out.append(ChartBollingerPointOut(time=_fmt(idx), upper=float(u), middle=float(m), lower=float(l)))
    return out


def _stochastic_points(full_k: pd.Series, full_d: pd.Series, mask: pd.Series) -> list[ChartStochasticPointOut]:
    out = []
    for idx in full_k.index[mask]:
        k, d = full_k.loc[idx], full_d.loc[idx]
        if pd.isna(k) or pd.isna(d):
            continue
        out.append(ChartStochasticPointOut(time=_fmt(idx), k=float(k), d=float(d)))
    return out


def _bar_points(df: pd.DataFrame, mask: pd.Series) -> list[ChartBarOut]:
    visible = df[mask]
    return [
        ChartBarOut(time=_fmt(idx), open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]))
        for idx, row in visible.iterrows()
    ]


def _filter_zones(lp_read: LiquidityZoneOut | None, visible_start: pd.Timestamp) -> list[ChartZoneOut]:
    """Liquidity Zone (LP) levels for one timeframe's read, restricted to
    zones whose establishing swing (formed_at) falls within this
    response's own VISIBLE window (visible_start, same cutoff the
    bars/indicator series are sliced against below) -- not the wider
    warm-up-inclusive fetch window, and not the LP feature's own
    independent num_zones cap (which already happened server-side, inside
    the nightly job). A zone established before visible_start is dropped
    entirely for this range, even if it's still unbreached/active --
    there's no bar on this chart for it to anchor against."""
    if lp_read is None:
        return []
    visible_start_date = visible_start.date()
    zones = []
    for side, zone_list in (("support", lp_read.support_zones), ("resistance", lp_read.resistance_zones)):
        for z in zone_list:
            if z.formed_at >= visible_start_date:
                zones.append(ChartZoneOut(side=side, price=z.price, formed_at=_fmt(z.formed_at)))
    return zones


def _marker_bar_time(visible_index: pd.DatetimeIndex, fired_at: datetime) -> pd.Timestamp | None:
    """The last visible bar whose date is <= fired_at's date. For a weekly
    view this naturally lands on the Monday-anchored week containing
    fired_at, since both resample_to_weekly and Yahoo's native interval="1wk"
    bars are indexed by each week's Monday (see weinstein.py). None if
    fired_at predates every visible bar -- shouldn't happen in practice
    given ACTIVE_WINDOW_DAYS=7 (entry_signal_data.py), but a marker with
    nothing to attach to is simply omitted rather than guessed at."""
    target = pd.Timestamp(fired_at.date())
    eligible = visible_index[visible_index <= target]
    return eligible[-1] if len(eligible) > 0 else None


async def get_chart_data(ticker: str, range_key: str) -> ChartOut:
    ticker = normalize_ticker(ticker)
    cfg = RANGE_CONFIG[range_key]

    bars_df, source = await _fetch_bars(ticker, range_key)

    # Independent of the bar fetch above -- this is a plain cache-only read
    # (see data/entry_signal_data.py), so it degrades to None on its own
    # regardless of whether bars_df came back empty.
    entry_signal = await get_entry_signal_data(ticker)
    entry_signal_available = entry_signal is not None

    # Also independent of the bar fetch -- another plain cache-only read
    # (see data/liquidity_zone_data.py), scoped to the same W1-W5
    # watchlists as entry_signal above (a separate nightly job,
    # so the two can occasionally diverge for a just-added ticker, but the
    # scope condition is the same). Unlike entry_signal, this one isn't
    # async -- it's a plain synchronous DB read, no live-fetch path exists
    # for this feature at all.
    liquidity_zones = get_liquidity_zone_data(ticker)
    zones_available = liquidity_zones is not None
    # visible_start doesn't depend on bars_df at all (today's date minus a
    # fixed per-range window), so it's computed here, ahead of the
    # empty-bars early return below, purely to filter zones -- the
    # bars/indicator slicing further down recomputes the identical value
    # for its own mask, since that half DOES need bars_df's index.
    visible_start = pd.Timestamp.today().normalize() - pd.Timedelta(days=cfg["visible_days"])
    lp_read = None
    if liquidity_zones is not None:
        lp_read = liquidity_zones.weekly if cfg["timeframe"] == "weekly" else liquidity_zones.daily
    zones = _filter_zones(lp_read, visible_start)

    if bars_df.empty:
        return ChartOut(
            range=range_key,
            timeframe=cfg["timeframe"],
            bars=[],
            ema21=[],
            sma50=[],
            sma200=[],
            bollinger=[],
            stochastic=[],
            rsi=[],
            entry_signal_marker=None,
            entry_signal_available=entry_signal_available,
            zones=[],
            zones_available=zones_available,
            source=source,
            chart_available=False,
        )

    close, high, low = bars_df["close"], bars_df["high"], bars_df["low"]

    ema21 = close.ewm(span=21, adjust=False).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    # Bollinger's basis is its own EMA(20) -- independent from the EMA21
    # trend line above (different span) and computed separately from
    # analysis.entry_signal.indicators.compute_bollinger_bands (which stays
    # SMA-basis, unmodified, since the BB+RSI entry-signal feature's
    # check_buy_signal depends on its SMA-basis pct_b). Only the basis
    # changes here -- stddev/window/multiplier are the same BB_LENGTH/BB_STD
    # that function uses.
    bb_basis = close.ewm(span=BB_LENGTH, adjust=False).mean()
    bb_sigma = close.rolling(BB_LENGTH).std(ddof=0)
    bb_upper = bb_basis + BB_STD * bb_sigma
    bb_lower = bb_basis - BB_STD * bb_sigma
    rsi_series = compute_rsi(close)
    full_k, full_d = compute_stochastic(high, low, close)

    mask = bars_df.index >= visible_start
    visible_index = bars_df.index[mask]

    marker = None
    if entry_signal is not None and entry_signal.active and entry_signal.fired_at is not None:
        bar_time = _marker_bar_time(visible_index, entry_signal.fired_at)
        if bar_time is not None:
            marker = ChartMarkerOut(time=_fmt(bar_time), label="BB+RSI")

    bars = _bar_points(bars_df, mask)

    return ChartOut(
        range=range_key,
        timeframe=cfg["timeframe"],
        bars=bars,
        ema21=_line_points(ema21, mask),
        sma50=_line_points(sma50, mask),
        sma200=_line_points(sma200, mask),
        bollinger=_bollinger_points(bb_upper, bb_basis, bb_lower, mask),
        stochastic=_stochastic_points(full_k, full_d, mask),
        rsi=_line_points(rsi_series, mask),
        entry_signal_marker=marker,
        entry_signal_available=entry_signal_available,
        zones=zones,
        zones_available=zones_available,
        source=source,
        # Mirrors Options Tracker's own api_position_chart convention:
        # "available" reads off the VISIBLE slice, not the full fetched
        # (warm-up-inclusive) history -- a ticker with some very old data but
        # nothing in the requested window should read as unavailable too.
        chart_available=bool(bars),
    )
