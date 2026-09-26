"""Orchestration layer for the ticker-page Chart tab -- OHLC candles plus
EMA21, SMA50/200, Bollinger(20,2, EMA basis), Full Stochastic(5,3,3, EMA), and
RSI(14), across four fixed views (D/6M, D/1Y, D/2Y, W/4Y). See CLAUDE.md's
Chart tab investigation notes for the full design history; the decisions
this module embodies:

1. Fully ON-DEMAND -- no new nightly cron job, no new precomputed table
   (confirmed fast enough for a page load in the latency investigation:
   median ~0.14s combined daily+weekly fetch, worst case ~0.56s). Every
   request computes fresh.
2. Zero persistent caching (deliberately reverted 2026-09-18 -- see
   CLAUDE.md's Chart tab entries for the FMP-cache staleness bug that
   caused this). `_fetch_bars` calls its provider directly on
   every request, with no persistence at all (the one exception, W_4Y's
   long-history store, is point 3c below) -- not
   clients/yahoo_cache.py's YahooPriceCache table (that cache's staleness
   check is coverage-blind: a row freshened by the 2y/4y nightly jobs would
   read as "fresh" even when this feature needs up to 10y of history for
   W_4Y).
3. **FMP-independent, unconditionally, non-dividend-adjusted (2026-09-18).**
   Previously this module branched on the FMP data-group state -- FMP's
   `/historical-price-eod/full` when enabled, Yahoo as the fallback. That
   branch is removed entirely: Chart is one of six technical-analysis
   features (alongside Weinstein Stage, Trend, Liquidity Zones, Warren,
   BB+RSI) moved off FMP, regardless of FMP data-group state, so a paused FMP
   subscription can never affect what candles this tab shows.
   `auto_adjust=False` is passed explicitly to every price fetch below --
   Yahoo's own default (True, still used by Price/Quote's unrelated
   fallback) is split/dividend-adjusted, which showed a confirmed ~1-7%
   divergence vs. FMP's raw closes for dividend-heavy tickers (O/UNH/F).
   Raw prices match what FMP was already showing, so this was also a
   continuity improvement for anyone who used this tab while FMP was still
   the default source.

3c. **W_4Y is FMP-first (P3, 2026-09-25).** FMP has no weekly endpoint, so the weekly bars are
    the ticker's ~10y of daily bars (clients/long_history_bars.py -- its OWN table, filled
    lazily on first view, topped up on a later stale view, gated on `daily_prices_long` for a
    US listing / `daily_prices_intl` for a non-US one) resampled with the existing
    analysis/trend_structure/weinstein.py::resample_to_weekly (Monday labels, first/max/min/
    last/sum -- verified identical to Yahoo's native `1wk` bars). This is the ONE place the
    Chart tab now persists anything (point 2's "zero caching" still holds for the daily ranges);
    the long-history table is refreshed close-aware, so it cannot show the stale-bar bug that
    motivated point 2. The Yahoo `1wk` fetch stays as the fall-through (group off with no row,
    FMP error, empty answer) and `ChartOut.source` says which one answered.

3b. **D_6M/D_1Y/D_2Y are FMP-first (P2 US, 2026-09-24; non-US added in P3, 2026-09-25).**
    `/historical-price-eod/full` (`daily_prices` group for a US listing,
    `daily_prices_intl` for a non-US one, whose phantom holiday/weekend bars are
    dropped; split- AND spin-off-adjusted, not dividend-adjusted) is tried first,
    live and uncached like everything else here; an empty answer, an error, or
    the group being off falls through to a live Yahoo fetch (Massive/Polygon, the
    middle tier of the 2026-09-23..2026-09-26 chain, was removed in Phase 6a).
    `ChartOut.source` is "fmp" | "yahoo".

4. **Earnings/dividend markers (2026-09-20)** are the one part of this
   module NOT Yahoo-only: data/chart_events_data.py fetches them live from FMP
   when the corporate_events group is live (Yahoo otherwise, or on FMP failure). Point 3's decision
   was about keeping technical-analysis INPUTS independent of the FMP
   subscription; event markers feed no indicator, and FMP's coverage is
   deeper for foreign issuers. Fetched concurrently with the candles and
   never able to fail or stall them.

Known, accepted asymmetry that closes over time: W_4Y shows 4 years of price
(RANGE_CONFIG's own visible_days), but signal-event markers only reach back as
far as events have actually been accumulated. Yahoo's own 2h-interval history
limit (~2 years, confirmed in the historical-backfill investigation) means no
event older than that can be computed today, so marker history started at
~2 years and grows by a day per day now that EVENT_RETENTION_DAYS (both
entry_signal_data's and warren_signal_data's) is 4 years -- it reaches a full 4
years around 2028-09 (BB+RSI) and 2029-03 (Warren). Until then the oldest part of
a W_4Y view simply has no markers to show -- expected, not a bug, and needs no
special-casing (_entry_signal_markers already returns an empty list for a
window with no matching events).
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta

import httpx
import pandas as pd
from sqlmodel import Session, select

from analysis.entry_signal.indicators import BB_LENGTH, BB_STD, compute_rsi
from analysis.trend_structure.stochastic import compute_stochastic
from analysis.trend_structure.weinstein import compute_stage_series, resample_to_weekly
from clients.daily_bar_sources import _profile_exchanges, fmp_rows_to_frame
from clients.fmp_client import fmp_client
from clients.long_history_bars import get_long_history
from clients.yahoo_client import yahoo_client
from core.data_groups import group_live
from core.db import engine
from core.models import TechnicalEntrySignalEvent, WarrenSignalEvent
from core.schemas import (
    ChartBarOut,
    ChartBollingerPointOut,
    ChartDividendMarkerOut,
    ChartEarningsMarkerOut,
    ChartLinePointOut,
    ChartMarkerOut,
    ChartOut,
    ChartStagePointOut,
    ChartStochasticPointOut,
    ChartZoneOut,
    LiquidityZoneOut,
)
from core.tickers import is_us_listed, normalize_ticker
from data.chart_events_data import DividendEvent, EarningsEvent, fetch_chart_events
from data.entry_signal_data import get_entry_signal_data
from data.liquidity_zone_data import get_liquidity_zone_data
from data.warren_signal_data import get_warren_signal_data
from helpers.weinstein_config import load_weinstein_params

# Human-readable label per Warren signal_kind -- everything else about a
# marker (color/shape/position) is a frontend styling decision keyed off
# `kind` itself, not this label.
_WARREN_KIND_LABELS = {
    "blue_up": "Blue Up",
    "yellow_up": "Yellow Up",
    "gray_up": "Gray Up",
    "blue_down": "Blue Down",
    "yellow_down": "Yellow Down",
    "gray_down": "Gray Down",
}

_EMPTY_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

logger = logging.getLogger(__name__)

# Per-range fetch/visible-window configuration. `yahoo_period` over-fetches
# slightly relative to the bare warm-up-plus-visible-window math (see
# CLAUDE.md) -- yfinance's period enum has no exact "2.8y" value, and a
# little extra fetched history costs nothing (indicators are computed on
# the full series and sliced afterward regardless), so it's snapped to the
# nearest covering value rather than fetched at exact precision.
# `lookback_days` is the equivalent exact-days figure used for the daily
# ranges' FMP request (an explicit from/to date range, not a period enum);
# only D_6M/D_1Y/D_2Y (the three daily ranges) have one.
RANGE_CONFIG: dict[str, dict] = {
    # Same yahoo_period as D_1Y -- already comfortably covers the ~1.3y
    # actually needed (182 visible days + ~200-bar SMA200 warm-up + margin);
    # only visible_days is halved.
    "D_6M": {"timeframe": "daily", "yahoo_period": "2y", "lookback_days": 730, "visible_days": 365 // 2},
    "D_1Y": {"timeframe": "daily", "yahoo_period": "2y", "lookback_days": 730, "visible_days": 365},
    "D_2Y": {"timeframe": "daily", "yahoo_period": "5y", "lookback_days": 1825, "visible_days": 365 * 2},
    # FMP-first (point 3c): the long-history daily bars trimmed to `history_days` and resampled
    # to weekly; the Yahoo native interval="1wk" fetch (`yahoo_period`) is the fall-through.
    "W_4Y": {"timeframe": "weekly", "yahoo_period": "10y", "history_days": 3650, "visible_days": 365 * 4},
}


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=_EMPTY_OHLCV_COLUMNS)


async def _fetch_yahoo_bars(ticker: str, range_key: str) -> pd.DataFrame:
    """Lowercase-column OHLCV DataFrame, empty (never None/raised) for a
    bad/delisted ticker or a fetch that returned nothing. auto_adjust=False
    explicitly -- see yahoo_client.get_history's own docstring for why its
    default (True) is wrong for this feature."""
    cfg = RANGE_CONFIG[range_key]
    interval = "1wk" if cfg["timeframe"] == "weekly" else "1d"
    result = await yahoo_client.get_history([ticker], period=cfg["yahoo_period"], interval=interval, auto_adjust=False)
    raw = result.get(ticker)
    if raw is None or raw.empty:
        return _empty_ohlcv()
    # yfinance's own native Open/High/Low/Close/Volume casing -> this
    # module's (and resample_to_weekly's) lowercase convention.
    return raw.rename(columns=str.lower)[_EMPTY_OHLCV_COLUMNS]


async def _fetch_fmp_weekly_bars(ticker: str, history_days: int) -> pd.DataFrame | None:
    """Weekly bars from the FMP long-history store, or None to fall through to Yahoo. Never
    raises: a store/FMP problem must degrade to the Yahoo fetch, not fail the chart. The
    in-progress week is emitted as a partial bar labelled by its Monday, as Yahoo does."""
    try:
        daily = await get_long_history(ticker)
    except Exception as exc:  # noqa: BLE001 -- fail soft, log the type only
        logger.warning("FMP long-history read failed for %s (%s); falling back to Yahoo", ticker, type(exc).__name__)
        return None
    if daily is None or daily.empty:
        return None
    daily = daily[daily.index >= pd.Timestamp.today().normalize() - pd.Timedelta(days=history_days)]
    weekly = resample_to_weekly(daily[_EMPTY_OHLCV_COLUMNS])
    return weekly if not weekly.empty else None


async def _fetch_bars(ticker: str, range_key: str) -> tuple[pd.DataFrame, str]:
    """Returns (lowercase-column OHLCV DataFrame, "fmp" | "yahoo").
    Empty DataFrame (never None/raised) for a bad/delisted ticker or a
    fetch that returned nothing from every source tried -- get_chart_data
    below is the single place that turns that into chart_available=False.

    W_4Y (weekly) is FMP-first via the long-history store, Yahoo native
    weekly as the fall-through -- see module docstring point 3c. The three daily ranges (D_6M/D_1Y/D_2Y) try FMP first, then a live Yahoo
    fetch -- reimplemented directly here (not via clients/daily_bar_sources.py or
    clients/shared_bars_cache.py) since this module stays zero-cache by design
    (point 2 above) and a single-ticker, no-state direct call is simpler than routing
    through the batch/cache-oriented machinery built for the nightly jobs."""
    cfg = RANGE_CONFIG[range_key]

    if cfg["timeframe"] == "weekly":
        weekly = await _fetch_fmp_weekly_bars(ticker, cfg["history_days"])
        if weekly is not None:
            return weekly, "fmp"
        df = await _fetch_yahoo_bars(ticker, range_key)
        return df, "yahoo"

    end = date.today()
    start = end - timedelta(days=cfg["lookback_days"])

    # FMP first, for US AND non-US listings (P3): a US listing is gated on `daily_prices`, a
    # non-US one on `daily_prices_intl` (whose rows also lose FMP's phantom holiday/weekend bars).
    us_listed = is_us_listed(ticker, _profile_exchanges([ticker]).get(ticker))
    fmp_group = "daily_prices" if us_listed else "daily_prices_intl"
    if group_live(fmp_group):
        try:
            df = fmp_rows_to_frame(
                await fmp_client.get_historical_price_eod(ticker, start.isoformat(), end.isoformat(), group=fmp_group),
                non_us=not us_listed,
            )
        except (httpx.HTTPError, ValueError):
            logger.warning("FMP daily-bar fetch failed for %s (%s); falling back", ticker, range_key)
            df = pd.DataFrame()
        if not df.empty:
            return df[_EMPTY_OHLCV_COLUMNS], "fmp"

    df = await _fetch_yahoo_bars(ticker, range_key)
    return df, "yahoo"


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


def _weinstein_overlay(bars_df: pd.DataFrame, mask: pd.Series) -> tuple[list[ChartLinePointOut], str, list[ChartStagePointOut]]:
    """W_4Y's "Stage" toggle data: the live-configured Weinstein MA line plus
    each visible week's stage. `bars_df` is already the weekly series (same
    Monday-labelled bars the engine resamples to), so this calls the engine's
    own compute_stage_series over the FULL fetched history -- the warm-up
    weeks before the visible window seed the sticky machine -- and only then
    slices to the visible window. Params are read live, never cached."""
    with Session(engine) as session:
        params = load_weinstein_params(session)
    stage_df = compute_stage_series(bars_df["close"], params)
    visible = stage_df[mask]
    stages = [ChartStagePointOut(time=_fmt(idx), stage=stage) for idx, stage in visible["stage"].items() if isinstance(stage, str)]
    return _line_points(stage_df["ma"], mask), f"{params.ma_type.upper()}{params.ma_length}", stages


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
    there's no bar on this chart for it to anchor against. The same
    formed_at cutoff also gates the at-most-one-per-side most-recently-
    breached zone (broken=True) -- it reuses the exact same LineSeries/
    formed_at-anchoring mechanism as an active zone, just in a distinct
    color, so it needs the same "no bar to anchor against" guard."""
    if lp_read is None:
        return []
    visible_start_date = visible_start.date()
    zones = []
    for side, zone_list in (("support", lp_read.support_zones), ("resistance", lp_read.resistance_zones)):
        for z in zone_list:
            if z.formed_at >= visible_start_date:
                zones.append(ChartZoneOut(side=side, price=z.price, formed_at=_fmt(z.formed_at)))
    for side, broken in (("support", lp_read.broken_support), ("resistance", lp_read.broken_resistance)):
        if broken is not None and broken.formed_at >= visible_start_date:
            zones.append(ChartZoneOut(side=side, price=broken.price, formed_at=_fmt(broken.formed_at), broken=True))
    return zones


def _marker_bar_time(visible_index: pd.DatetimeIndex, fired_at: datetime) -> pd.Timestamp | None:
    """The last visible bar whose date is <= fired_at's date. For a weekly
    view this naturally lands on the Monday-anchored week containing
    fired_at, since both resample_to_weekly and Yahoo's native interval="1wk"
    bars are indexed by each week's Monday (see weinstein.py) -- this is
    also, deliberately, the SAME bucketing _entry_signal_markers below
    relies on to group multiple historical fires onto one bar: reusing one
    function for both the daily-day and weekly-week cases keeps a marker's
    bucket byte-identical to how the chart's own bars are bucketed, rather
    than maintaining a second, parallel week-anchoring rule that could
    drift from resample_to_weekly's. None if fired_at predates every
    visible bar -- a marker with nothing to attach to is simply omitted
    rather than guessed at (this is expected, not an error, for an old
    fire outside the visible window -- see get_chart_data's own comment on
    the W_4Y/event-retention asymmetry)."""
    target = pd.Timestamp(fired_at.date())
    eligible = visible_index[visible_index <= target]
    return eligible[-1] if len(eligible) > 0 else None


def _fetch_entry_signal_events(ticker: str, since: pd.Timestamp) -> list[TechnicalEntrySignalEvent]:
    """Every recorded historical fire for `ticker` at or after `since`
    (the response's own visible_start, as a lower-bound optimization only
    -- an event older than that would map to bar_time=None in
    _entry_signal_markers below anyway and get dropped, so this doesn't
    affect correctness, just how many rows get fetched). Ordered
    chronologically so _entry_signal_markers' "first assignment per bucket
    wins" logic is correct without a second sort."""
    with Session(engine) as session:
        stmt = (
            select(TechnicalEntrySignalEvent)
            .where(TechnicalEntrySignalEvent.ticker == ticker, TechnicalEntrySignalEvent.fired_at >= since)
            .order_by(TechnicalEntrySignalEvent.fired_at)
        )
        return list(session.exec(stmt).all())


def _entry_signal_markers(visible_index: pd.DatetimeIndex, events: list[TechnicalEntrySignalEvent]) -> list[ChartMarkerOut]:
    """One marker per bar in visible_index with at least one real fire,
    keeping the FIRST chronological fire when more than one event maps to
    the same bar -- i.e. the same exchange-calendar day for a daily view,
    or the same Monday-anchored week for the weekly view, per
    _marker_bar_time's own bucketing. `events` must already be ordered
    chronologically (see _fetch_entry_signal_events) so "skip a bucket
    already seen" below correctly keeps the first, not an arbitrary, fire.

    First (not last) is a deliberate choice, not a default: a historical
    marker answers "when did this setup first appear," which is what a
    viewer scanning the chart for past occurrences of this pattern wants
    to see -- confirmed via a real 6-ticker, 2-year sample that ~56% of
    firing days fire 2+ times in the same session (an oversold reading
    tends to persist across consecutive 2h bars during one drawdown leg),
    so this is a frequent, load-bearing choice, not a rare tie-break.
    Unlike TechnicalEntrySignal's own "latest fire" semantics (last wins,
    by design, for its own "is there a live signal right now" purpose --
    left completely unchanged), this function serves a different
    question, so it deliberately answers it differently."""
    first_fire_bar: dict[pd.Timestamp, None] = {}
    for event in events:
        bar_time = _marker_bar_time(visible_index, event.fired_at)
        if bar_time is None or bar_time in first_fire_bar:
            continue
        first_fire_bar[bar_time] = None
    return [ChartMarkerOut(time=_fmt(bt), label="BB+RSI", kind="bb_rsi") for bt in sorted(first_fire_bar)]


def _fetch_warren_signal_events(ticker: str, since: pd.Timestamp) -> list[WarrenSignalEvent]:
    """Warren's own counterpart to _fetch_entry_signal_events above --
    same lower-bound-only `since` optimization, same chronological
    ordering."""
    with Session(engine) as session:
        stmt = select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == ticker, WarrenSignalEvent.fired_at >= since).order_by(WarrenSignalEvent.fired_at)
        return list(session.exec(stmt).all())


def _warren_signal_markers(visible_index: pd.DatetimeIndex, events: list[WarrenSignalEvent]) -> list[ChartMarkerOut]:
    """Same first-fire-per-bucket tie-break as _entry_signal_markers above,
    but grouped by (bucket, signal_kind) rather than bucket alone -- two
    DIFFERENT arrows (e.g. a Blue Up and a Yellow Up) can genuinely fire on
    the same bar (see models.py::WarrenSignalEvent's own comment) and must
    both render as distinct markers, while multiple fires of the SAME kind
    in one bucket still collapse to the first."""
    first_fire_bar: dict[tuple[pd.Timestamp, str], None] = {}
    for event in events:
        bar_time = _marker_bar_time(visible_index, event.fired_at)
        if bar_time is None:
            continue
        key = (bar_time, event.signal_kind)
        if key in first_fire_bar:
            continue
        first_fire_bar[key] = None
    return [
        ChartMarkerOut(time=_fmt(bt), label=_WARREN_KIND_LABELS[kind], kind=kind)
        for bt, kind in sorted(first_fire_bar, key=lambda k: (k[0], k[1]))
    ]


def _bucket_events(visible_index: pd.DatetimeIndex, events: list, timeframe: str) -> dict[pd.Timestamp, list]:
    """Groups events onto the visible bar each one belongs to, chronologically
    within a bar. Reuses _marker_bar_time, so an event's bucket is
    byte-identical to how the signal markers above (and the bars themselves)
    are bucketed -- including landing a weekly view's event on its
    Monday-anchored week bar.

    Two drops, both deliberate:
    - Events before the first visible bar have nothing to attach to (the
      visible window, not the wider warm-up-inclusive fetch, is the filter --
      same rule LP zones follow), which _marker_bar_time already reports as
      None.
    - Events AFTER the last bar. Unlike a recorded signal fire, an event feed
      is forward-looking (FMP lists the next scheduled earnings date and
      declared-ahead ex-dates), and _marker_bar_time would happily snap a
      future date back onto the last bar, presenting a scheduled event as one
      that already happened. The cutoff is the last bar's own date for a daily
      view, or that week's Sunday for the weekly view (whose last bar is
      indexed by its Monday) -- and never later than today, since the
      current, still-forming weekly bar spans days that haven't happened."""
    if len(visible_index) == 0:
        return {}
    last_bar = visible_index[-1].date()
    cutoff = min(date.today(), last_bar + timedelta(days=6 if timeframe == "weekly" else 0))
    buckets: dict[pd.Timestamp, list] = {}
    for event in sorted(events, key=lambda e: e.event_date):
        if event.event_date > cutoff:
            continue
        bar_time = _marker_bar_time(visible_index, datetime.combine(event.event_date, time.min))
        if bar_time is None:
            continue
        buckets.setdefault(bar_time, []).append(event)
    return buckets


def _earnings_markers(visible_index: pd.DatetimeIndex, events: list[EarningsEvent], timeframe: str) -> list[ChartEarningsMarkerOut]:
    """One marker per bar. Two reports never legitimately share a bar (they
    are a quarter apart), so a collision means duplicated/restated feed rows --
    keep the first."""
    out = []
    for bar_time, bucket in sorted(_bucket_events(visible_index, events, timeframe).items()):
        ev = bucket[0]
        out.append(
            ChartEarningsMarkerOut(
                time=_fmt(bar_time), event_date=_fmt(ev.event_date), eps_actual=ev.eps_actual, eps_estimated=ev.eps_estimated
            )
        )
    return out


def _dividend_markers(visible_index: pd.DatetimeIndex, events: list[DividendEvent], timeframe: str) -> list[ChartDividendMarkerOut]:
    """One marker per bar. Unlike earnings, several ex-dates in one bar are
    real (a regular plus a special dividend in the same week -- or, in the
    weekly view, any two close together), and the price impact is their sum,
    so amounts add and the earlier ex-date is reported."""
    out = []
    for bar_time, bucket in sorted(_bucket_events(visible_index, events, timeframe).items()):
        out.append(
            ChartDividendMarkerOut(time=_fmt(bar_time), event_date=_fmt(bucket[0].event_date), amount=sum(e.amount for e in bucket))
        )
    return out


async def get_chart_data(ticker: str, range_key: str) -> ChartOut:
    ticker = normalize_ticker(ticker)
    cfg = RANGE_CONFIG[range_key]

    # Concurrent: the events fetch (two live FMP calls, ~1s) is independent of
    # the candles, and serializing them would add its whole latency to every
    # range switch. fetch_chart_events never raises and self-limits its own
    # runtime, so it can't fail or stall the candles.
    (bars_df, source), events_read = await asyncio.gather(_fetch_bars(ticker, range_key), fetch_chart_events(ticker))

    # Independent of the bar fetch above -- this is a plain cache-only read
    # (see data/entry_signal_data.py), so it degrades to None on its own
    # regardless of whether bars_df came back empty.
    entry_signal = await get_entry_signal_data(ticker)
    entry_signal_available = entry_signal is not None

    # Warren's own counterpart -- same cache-only, degrade-to-null
    # convention, independent of everything else in this function.
    warren_signal = await get_warren_signal_data(ticker)
    warren_signal_available = warren_signal is not None

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
            entry_signal_markers=[],
            entry_signal_available=entry_signal_available,
            warren_signal_markers=[],
            warren_signal_available=warren_signal_available,
            zones=[],
            zones_available=zones_available,
            events_source=events_read.source,
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

    # Independent of entry_signal/entry_signal_available above -- history
    # is sourced from TechnicalEntrySignalEvent, not TechnicalEntrySignal,
    # and deliberately ignores entry_signal.active's 7-day window: that
    # gate answers "is there a live signal right now," which has no
    # bearing on whether a past fire should still show as a historical
    # marker. A ticker that's tracked but has never fired gets an empty
    # list here, not an omitted field -- entry_signal_available is what
    # distinguishes "not tracked" from "tracked, nothing fired."
    events = _fetch_entry_signal_events(ticker, visible_start) if entry_signal_available else []
    markers = _entry_signal_markers(visible_index, events)

    # Warren's own history fetch/marker-grouping, independent of BB+RSI's
    # above -- see _warren_signal_markers' own docstring for why it groups
    # by (bucket, signal_kind) rather than bucket alone.
    warren_events = _fetch_warren_signal_events(ticker, visible_start) if warren_signal_available else []
    warren_markers = _warren_signal_markers(visible_index, warren_events)

    # Corporate-event markers, bucketed onto the same visible bars as
    # everything above. An empty list with events_source set means "fetched,
    # nothing in this window"; events_source=None means the fetch failed.
    earnings_markers = _earnings_markers(visible_index, events_read.earnings, cfg["timeframe"])
    dividend_markers = _dividend_markers(visible_index, events_read.dividends, cfg["timeframe"])

    bars = _bar_points(bars_df, mask)

    weinstein_ma, weinstein_ma_label, weinstein_stages = _weinstein_overlay(bars_df, mask) if cfg["timeframe"] == "weekly" else ([], None, [])

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
        entry_signal_markers=markers,
        entry_signal_available=entry_signal_available,
        weinstein_ma=weinstein_ma,
        weinstein_ma_label=weinstein_ma_label,
        weinstein_stages=weinstein_stages,
        warren_signal_markers=warren_markers,
        warren_signal_available=warren_signal_available,
        zones=zones,
        zones_available=zones_available,
        earnings_markers=earnings_markers,
        dividend_markers=dividend_markers,
        events_source=events_read.source,
        source=source,
        # Mirrors Options Tracker's own api_position_chart convention:
        # "available" reads off the VISIBLE slice, not the full fetched
        # (warm-up-inclusive) history -- a ticker with some very old data but
        # nothing in the requested window should read as unavailable too.
        chart_available=bool(bars),
    )
