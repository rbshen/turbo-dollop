import asyncio
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import data.chart_data as chart_data
from analysis.trend_structure.weinstein import resample_to_weekly
from core.models import TechnicalEntrySignalEvent, WarrenSignalEvent
from core.schemas import BrokenZoneOut, LiquidityZoneOut, LiquidityZonesOut, TechnicalEntrySignalOut, ZoneOut
from data.chart_events_data import ChartEvents, DividendEvent, EarningsEvent


def _daily_df(n: int, *, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """n business-day bars ending at `end` (default: today). Closes oscillate
    (rising trend + a sine wiggle) rather than moving in one direction every
    single bar -- a strictly monotonic series never has a single down day,
    which makes RSI's avg_loss zero for the whole series and so, correctly,
    all-NaN (see compute_rsi's own avg_loss.replace(0, nan) guard) -- not a
    bug, just not a realistic fixture for exercising RSI here."""
    import math

    end = end or pd.Timestamp.today().normalize()
    index = pd.bdate_range(end=end, periods=n)
    closes = pd.Series([100.0 + i * 0.1 + 5.0 * math.sin(i / 3.0) for i in range(n)], index=index)
    return pd.DataFrame(
        {
            "open": closes - 0.5,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": 1000,
        },
        index=index,
    )


def _entry_signal(*, active: bool, fired_at: datetime | None) -> TechnicalEntrySignalOut:
    now = datetime.now()
    return TechnicalEntrySignalOut(
        ticker="TEST",
        signal_type="bb_rsi",
        timeframe="2h",
        active=active,
        fired_at=fired_at,
        pct_b=0.02,
        rsi=25.0,
        close=101.5,
        stop_price=98.0,
        source="fmp",
        as_of=now,
        computed_at=now,
    )


async def _no_entry_signal(ticker: str):
    return None


def _events(ticker: str, fired_ats: list[datetime]) -> list[TechnicalEntrySignalEvent]:
    return [
        TechnicalEntrySignalEvent(ticker=ticker, signal_type="bb_rsi", timeframe="2h", fired_at=fa, stop_price=95.0, created_at=fa)
        for fa in sorted(fired_ats)
    ]


def _warren_signal(*, active: bool, fired_at: datetime | None, signal_kind: str | None) -> TechnicalEntrySignalOut:
    now = datetime.now()
    return TechnicalEntrySignalOut(
        ticker="TEST",
        signal_type="warren",
        timeframe="2h",
        active=active,
        fired_at=fired_at,
        rsi=25.0,
        close=101.5,
        stop_price=98.0,
        signal_kind=signal_kind,
        gray_suppressed=False,
        stop_count=0,
        source="fmp",
        as_of=now,
        computed_at=now,
    )


async def _no_warren_signal(ticker: str):
    return None


@pytest.fixture(autouse=True)
def _default_no_warren_signal(monkeypatch):
    # Every test in this file must patch get_warren_signal_data to SOME
    # value -- chart_data.get_chart_data now calls it unconditionally, and
    # without a default stub these otherwise-unrelated tests would silently
    # read against the real, on-disk core.db.engine instead of a fixture
    # value (a real fixed/fake ticker like "TEST"/"BADTICKER" would read
    # back None either way, but this app's own test-isolation convention --
    # see CLAUDE.md's fixture-contamination section -- is to never leave a
    # module's DB-backed function unpatched in a test, reads included).
    # Tests exercising Warren's own marker behavior override this via their
    # own monkeypatch.setattr call, which takes precedence.
    monkeypatch.setattr(chart_data, "get_warren_signal_data", _no_warren_signal)


@pytest.fixture(autouse=True)
def _fresh_chart_data_engine(monkeypatch):
    # chart_data reads WeinsteinSettings (lazy-seeded => a WRITE on first read) for
    # the W_4Y Stage overlay; never let that reach the real core.db.engine.
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(chart_data, "engine", eng)
    return eng


@pytest.fixture(autouse=True)
def _default_no_chart_events(monkeypatch):
    # get_chart_data reads earnings/dividends from the CorporateEvent cache on every
    # call; without a default stub every unrelated test in this file would
    # read the real core.db.engine. Tests exercising the event markers override
    # this via their own monkeypatch.setattr, which takes precedence.
    async def _none(ticker):
        return ChartEvents()

    monkeypatch.setattr(chart_data, "fetch_chart_events", _none)


def _warren_events(ticker: str, fired_ats_and_kinds: list[tuple[datetime, str]]) -> list[WarrenSignalEvent]:
    return [
        WarrenSignalEvent(ticker=ticker, timeframe="2h", signal_kind=kind, fired_at=fa, stop_price=95.0, created_at=fa)
        for fa, kind in sorted(fired_ats_and_kinds, key=lambda x: x[0])
    ]


def _no_zones(ticker: str):
    return None


def _zone_out(price: float, formed_at: str) -> ZoneOut:
    return ZoneOut(price=price, distance_pct=0.0, cluster_size=1, formed_at=date.fromisoformat(formed_at))


def _broken_zone_out(price: float, formed_at: str, breached_at: str) -> BrokenZoneOut:
    return BrokenZoneOut(price=price, distance_pct=0.0, formed_at=date.fromisoformat(formed_at), breached_at=date.fromisoformat(breached_at))


def _lp_out(
    *,
    support: list[ZoneOut],
    resistance: list[ZoneOut],
    broken_support: BrokenZoneOut | None = None,
    broken_resistance: BrokenZoneOut | None = None,
) -> LiquidityZoneOut:
    now = datetime.now()
    return LiquidityZoneOut(
        timeframe="daily",
        last_price=100.0,
        as_of=now.date(),
        computed_at=now,
        source="fmp",
        support_zones=support,
        resistance_zones=resistance,
        broken_support=broken_support,
        broken_resistance=broken_resistance,
    )


def _patch_bars(monkeypatch, df: pd.DataFrame) -> None:
    """Feeds chart_data's two FMP fetch paths from `df` (lowercase-column, daily-frequency, as
    _daily_df produces, or an empty frame to simulate no data): the D ranges' direct
    `/historical-price-eod/full` call, and W_4Y's long-history store (whose dailies chart_data
    resamples to weekly itself with the real resample_to_weekly)."""
    rows = [] if df.empty else [
        {"date": ts.strftime("%Y-%m-%d"), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
        for ts, r in df.iloc[::-1].iterrows()
    ]

    async def fake_fmp(ticker, from_date, to_date, group="daily_prices"):
        return rows

    async def fake_long_history(ticker):
        return None if df.empty else df

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", fake_fmp)
    monkeypatch.setattr(chart_data, "get_long_history", fake_long_history)


def _fmp_rows(n: int = 600) -> list[dict]:
    d = _daily_df(n)
    return [
        {"date": ts.strftime("%Y-%m-%d"), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
        for ts, r in d.iloc[::-1].iterrows()
    ]


def _patch_fmp_bars(monkeypatch, rows, *, raises: bool = False, groups: list[str] | None = None) -> list[str]:
    calls: list[str] = []

    async def fake(ticker, from_date, to_date, group="daily_prices"):
        calls.append(ticker)
        if groups is not None:
            groups.append(group)
        if raises:
            raise httpx.ConnectError("boom")
        return rows

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", fake)
    return calls


def _no_other_sources(monkeypatch):
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)


def test_daily_range_is_fmp_first_for_us_tickers(monkeypatch):
    calls = _patch_fmp_bars(monkeypatch, _fmp_rows())
    _no_other_sources(monkeypatch)
    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))
    assert out.source == "fmp" and out.chart_available and calls == ["AAPL"]


def test_daily_range_is_an_empty_chart_when_fmp_is_empty_or_errors(monkeypatch):
    for kwargs in ({}, {"raises": True}):
        _patch_fmp_bars(monkeypatch, [], **kwargs)
        monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
        monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
        out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))
        assert out.chart_available is False and out.bars == []  # no fallback, no stale substitute


def test_daily_range_is_an_empty_chart_without_calling_fmp_when_daily_prices_is_off(monkeypatch):
    import core.data_groups as dg

    dg.set_group_enabled("daily_prices", False)
    calls = _patch_fmp_bars(monkeypatch, _fmp_rows())
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))
    assert out.chart_available is False and out.bars == [] and calls == []


def test_w_4y_reads_the_long_history_store_through_the_same_fmp_client(monkeypatch):
    """W_4Y: the store fetches via the FMP client (group daily_prices_long), and D ranges never
    touch the store."""
    groups: list[str] = []
    calls = _patch_fmp_bars(monkeypatch, _fmp_rows(2600), groups=groups)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    assert asyncio.run(chart_data.get_chart_data("AAPL", "W_4Y")).source == "fmp"
    assert groups == ["daily_prices_long"] and calls == ["AAPL"]


def test_w_4y_is_an_empty_chart_when_fmp_has_nothing(monkeypatch):
    _patch_fmp_bars(monkeypatch, [], raises=True)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "W_4Y"))
    assert out.chart_available is False and out.bars == []


def test_chart_available_false_when_fetch_returns_no_bars(monkeypatch):
    _patch_bars(monkeypatch, pd.DataFrame())
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("BADTICKER", "D_1Y"))

    assert out.chart_available is False
    assert out.bars == []
    assert out.ema21 == out.sma50 == out.sma200 == []
    assert out.entry_signal_available is False
    assert out.entry_signal_markers == []
    assert out.source == "fmp"


def test_daily_range_computes_full_warmup_then_slices_to_visible_window(monkeypatch):
    # 600 business days (~2.4y) fetched, of which D_1Y only shows the
    # trailing ~365 calendar days -- plenty of warm-up headroom before the
    # visible window starts, so every visible bar should have a real
    # (non-NaN) SMA200 once sliced.
    df = _daily_df(600)

    _patch_bars(monkeypatch, df)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))

    assert out.chart_available is True
    assert out.timeframe == "daily"
    assert 0 < len(out.bars) < 600  # sliced down from the full fetched history
    # Every visible bar has a real SMA200 -- confirms the warm-up (fetched
    # but not visible) portion of the series was included in the rolling
    # computation before slicing, not computed on the visible slice alone.
    assert len(out.sma200) == len(out.bars)
    assert len(out.ema21) == len(out.bars)
    assert len(out.bollinger) == len(out.bars)
    assert len(out.rsi) > 0
    assert len(out.stochastic) > 0


def test_d6m_range_computes_full_warmup_then_slices_to_visible_window(monkeypatch):
    # Same shape as the D_1Y warm-up test above, at D_6M's own (shorter)
    # visible window -- 600 business days (~2.4y) fetched, of which D_6M
    # only shows the trailing ~182 calendar days.
    df = _daily_df(600)

    _patch_bars(monkeypatch, df)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_6M"))

    assert out.chart_available is True
    assert out.timeframe == "daily"
    assert 0 < len(out.bars) < 600
    # Every visible bar has a real SMA200 -- confirms the warm-up (fetched
    # but not visible) portion of the series was included in the rolling
    # computation before slicing, not computed on the visible slice alone.
    assert len(out.sma200) == len(out.bars)
    assert len(out.ema21) == len(out.bars)
    assert len(out.bollinger) == len(out.bars)


def test_ema21_is_exponential_not_a_rolling_average(monkeypatch):
    # A trend-line switch, not just a rename -- confirms the series is
    # actually close.ewm(span=21, adjust=False).mean(), not SMA20 (or any
    # other rolling mean) under a new field name.
    df = _daily_df(300)

    _patch_bars(monkeypatch, df)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))

    expected_ema21 = df["close"].ewm(span=21, adjust=False).mean()
    expected_sma20 = df["close"].rolling(20).mean()
    last = out.ema21[-1]
    last_idx = df.index[df.index.strftime("%Y-%m-%d") == last.time][0]

    assert last.value == pytest.approx(float(expected_ema21.loc[last_idx]), abs=1e-6)
    # Confirms this genuinely differs from the old SMA20 series, not just a
    # renamed field holding the same values.
    assert last.value != pytest.approx(float(expected_sma20.loc[last_idx]), abs=1e-6)


def test_bollinger_basis_is_ema20_not_sma20(monkeypatch):
    # Basis is EMA(20) now; stddev/window/multiplier are unchanged from the
    # shared BB_LENGTH/BB_STD constants -- only the basis calculation moved.
    df = _daily_df(300)

    _patch_bars(monkeypatch, df)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "D_1Y"))

    close = df["close"]
    expected_ema20 = close.ewm(span=20, adjust=False).mean()
    expected_sma20 = close.rolling(20).mean()
    expected_sigma = close.rolling(20).std(ddof=0)

    last = out.bollinger[-1]
    last_idx = df.index[df.index.strftime("%Y-%m-%d") == last.time][0]

    assert last.middle == pytest.approx(float(expected_ema20.loc[last_idx]), abs=1e-6)
    assert last.middle != pytest.approx(float(expected_sma20.loc[last_idx]), abs=1e-6)
    assert (last.upper - last.middle) == pytest.approx(2.0 * float(expected_sigma.loc[last_idx]), abs=1e-6)
    assert (last.middle - last.lower) == pytest.approx(2.0 * float(expected_sigma.loc[last_idx]), abs=1e-6)


def test_w4y_range_resamples_the_long_history_dailies_to_weekly_monday_bars(monkeypatch):
    _patch_bars(monkeypatch, _daily_df(1300))  # ~5y of business days
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("AAPL", "W_4Y"))

    assert out.source == "fmp" and out.chart_available is True
    days = [datetime.strptime(b.time, "%Y-%m-%d") for b in out.bars]
    assert all(d.weekday() == 0 for d in days)  # weekly bars labelled by their Monday
    assert all((b - a).days == 7 for a, b in zip(days, days[1:]))


def test_entry_signal_not_tracked(monkeypatch):
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("NOTTRACKED", "D_1Y"))

    assert out.entry_signal_available is False
    assert out.entry_signal_markers == []


def test_entry_signal_tracked_but_no_events_in_window_has_no_markers(monkeypatch):
    # "active" (TechnicalEntrySignal's own 7-day window) no longer gates
    # history at all -- what matters now is purely whether
    # TechnicalEntrySignalEvent has any rows in the visible window. Here
    # the ticker IS tracked (entry_signal_available=True) but the event
    # table has nothing for it.
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)

    async def fake_entry_signal(ticker):
        return _entry_signal(active=False, fired_at=datetime.now() - timedelta(days=10))

    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: [])

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.entry_signal_available is True
    assert out.entry_signal_markers == []


def test_entry_signal_places_a_marker_per_event_even_when_inactive(monkeypatch):
    # A single old, long-INACTIVE fire (TechnicalEntrySignal.active would
    # read False -- outside its own 7-day window) must still produce a
    # historical marker: the active gate is a TechnicalEntrySignal-only
    # concept and deliberately does not apply to entry_signal_markers.
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)

    fired_at = (pd.Timestamp.today().normalize() - pd.Timedelta(days=60)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=False, fired_at=fired_at)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [fired_at]))

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.entry_signal_available is True
    assert len(out.entry_signal_markers) == 1
    assert out.entry_signal_markers[0].label == "BB+RSI"
    marker_date = datetime.strptime(out.entry_signal_markers[0].time, "%Y-%m-%d").date()
    assert marker_date <= fired_at.date()
    assert (fired_at.date() - marker_date).days <= 3  # nearest trading bar on/before a weekday fired_at


def test_entry_signal_multiple_fires_same_day_collapse_to_one_marker_keeping_first(monkeypatch):
    # The confirmed real-world shape from the historical-backfill
    # investigation: ~56% of firing days fire 2+ times in the same
    # session. Three events land on the exact same calendar day here --
    # they must collapse to ONE marker, anchored to the FIRST
    # chronological fire, not the last.
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)

    day = pd.Timestamp.today().normalize() - pd.Timedelta(days=5)
    first_fire = (day + pd.Timedelta(hours=11, minutes=30)).to_pydatetime()
    second_fire = (day + pd.Timedelta(hours=13, minutes=30)).to_pydatetime()
    third_fire = (day + pd.Timedelta(hours=15, minutes=30)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=third_fire)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(
        chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [first_fire, second_fire, third_fire])
    )

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert len(out.entry_signal_markers) == 1  # not 3
    marker_date = datetime.strptime(out.entry_signal_markers[0].time, "%Y-%m-%d").date()
    assert marker_date <= first_fire.date()
    assert (first_fire.date() - marker_date).days <= 3


def test_entry_signal_distinct_days_each_get_their_own_marker(monkeypatch):
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)

    today = pd.Timestamp.today().normalize()
    fired_1 = (today - pd.Timedelta(days=30)).to_pydatetime()
    fired_2 = (today - pd.Timedelta(days=10)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=fired_2)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [fired_1, fired_2]))

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert len(out.entry_signal_markers) == 2
    times = sorted(out.entry_signal_markers, key=lambda m: m.time)
    assert times[0].time < times[1].time


def test_entry_signal_weekly_view_collapses_same_week_fires_keeping_first(monkeypatch):
    # Same multi-fire-per-bucket shape as the daily test above, but for
    # the W_4Y (weekly) view -- two fires in the same Monday-anchored
    # week must collapse to one marker on that week's bar, keeping the
    # earlier of the two.
    df = _daily_df(365 * 5)  # enough history for W_4Y's warm-up + 4y visible window
    _patch_bars(monkeypatch, df)

    # Two fires in the same calendar week (a Tuesday and a Thursday),
    # comfortably inside the visible window.
    monday = pd.Timestamp.today().normalize() - pd.Timedelta(days=180)
    monday = monday - pd.Timedelta(days=monday.weekday())  # snap to that week's Monday
    tuesday_fire = (monday + pd.Timedelta(days=1, hours=11, minutes=30)).to_pydatetime()
    thursday_fire = (monday + pd.Timedelta(days=3, hours=13, minutes=30)).to_pydatetime()

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=thursday_fire)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(
        chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [tuesday_fire, thursday_fire])
    )

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "W_4Y"))

    assert out.timeframe == "weekly"
    assert len(out.entry_signal_markers) == 1  # both fires collapse onto the same week's bar
    marker_date = date.fromisoformat(out.entry_signal_markers[0].time)
    assert marker_date == monday.date()  # anchored to the week's Monday, matching resample_to_weekly


def test_entry_signal_w4y_shows_no_markers_for_the_older_two_years_not_an_error(monkeypatch):
    # The documented, accepted asymmetry: W_4Y shows 4 years of price but
    # stored events only reach back as far as they have accumulated (the 2h-interval
    # history limits how far back they can be computed to ~2 years; retention is 4 --
    # see chart_data's own module docstring). Simulates that by only returning
    # events within the most recent ~2 years -- the older part of the visible
    # window must simply have no markers, not raise or degrade the chart.
    df = _daily_df(365 * 5)
    _patch_bars(monkeypatch, df)

    recent_fire = (pd.Timestamp.today().normalize() - pd.Timedelta(days=200)).to_pydatetime()  # well within 2y

    async def fake_entry_signal(ticker):
        return _entry_signal(active=True, fired_at=recent_fire)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", fake_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    # Simulates the real query already having nothing older than ~2 years
    # to return (pruned/never backfilled that far back) -- only the one
    # recent event exists at all.
    monkeypatch.setattr(chart_data, "_fetch_entry_signal_events", lambda ticker, since: _events(ticker, [recent_fire]))

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "W_4Y"))

    assert out.chart_available is True  # the rest of the chart renders normally
    assert out.timeframe == "weekly"
    assert len(out.entry_signal_markers) == 1  # only the one recent fire -- no error, no fabricated old markers
    marker_date = date.fromisoformat(out.entry_signal_markers[0].time)
    assert marker_date <= recent_fire.date()


def test_warren_signal_not_tracked(monkeypatch):
    _patch_bars(monkeypatch, _daily_df(300))
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    # get_warren_signal_data stays the module's default (_no_warren_signal)
    # via the autouse fixture -- not overridden here.

    out = asyncio.run(chart_data.get_chart_data("UNTRACKED", "D_1Y"))

    assert out.warren_signal_available is False
    assert out.warren_signal_markers == []


def test_warren_signal_places_a_marker_per_event_with_its_own_kind_and_label(monkeypatch):
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)

    fired_at = (pd.Timestamp.today().normalize() - pd.Timedelta(days=60)).to_pydatetime()

    async def fake_warren_signal(ticker):
        return _warren_signal(active=False, fired_at=fired_at, signal_kind="gray_up")

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "get_warren_signal_data", fake_warren_signal)
    monkeypatch.setattr(chart_data, "_fetch_warren_signal_events", lambda ticker, since: _warren_events(ticker, [(fired_at, "gray_up")]))

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.warren_signal_available is True
    assert len(out.warren_signal_markers) == 1
    marker = out.warren_signal_markers[0]
    assert marker.kind == "gray_up"
    assert marker.label == "Gray Up"
    # BB+RSI's own markers are untouched by any of this -- confirms the
    # two marker streams are genuinely independent, not accidentally merged.
    assert out.entry_signal_markers == []


def test_warren_signal_two_different_kinds_on_the_same_bar_both_render(monkeypatch):
    # The exact scenario that ruled out reusing TechnicalEntrySignalEvent's
    # UniqueConstraint for Warren's own history table -- see
    # models.py::WarrenSignalEvent's own comment. Confirms the Chart tab
    # marker layer preserves both, rather than collapsing them the way two
    # SAME-kind fires on one bucket correctly do.
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)

    day = pd.Timestamp.today().normalize() - pd.Timedelta(days=5)
    same_bar = (day + pd.Timedelta(hours=11, minutes=30)).to_pydatetime()

    async def fake_warren_signal(ticker):
        return _warren_signal(active=True, fired_at=same_bar, signal_kind="blue_up")

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "get_warren_signal_data", fake_warren_signal)
    monkeypatch.setattr(
        chart_data,
        "_fetch_warren_signal_events",
        lambda ticker, since: _warren_events(ticker, [(same_bar, "blue_up"), (same_bar, "yellow_up")]),
    )

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert len(out.warren_signal_markers) == 2
    assert {m.kind for m in out.warren_signal_markers} == {"blue_up", "yellow_up"}
    assert all(m.time == out.warren_signal_markers[0].time for m in out.warren_signal_markers)


def test_warren_signal_multiple_fires_of_the_same_kind_same_day_collapse_to_one(monkeypatch):
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)

    day = pd.Timestamp.today().normalize() - pd.Timedelta(days=5)
    first_fire = (day + pd.Timedelta(hours=11, minutes=30)).to_pydatetime()
    second_fire = (day + pd.Timedelta(hours=13, minutes=30)).to_pydatetime()

    async def fake_warren_signal(ticker):
        return _warren_signal(active=True, fired_at=second_fire, signal_kind="yellow_up")

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "get_warren_signal_data", fake_warren_signal)
    monkeypatch.setattr(
        chart_data,
        "_fetch_warren_signal_events",
        lambda ticker, since: _warren_events(ticker, [(first_fire, "yellow_up"), (second_fire, "yellow_up")]),
    )

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert len(out.warren_signal_markers) == 1  # not 2 -- same kind, same bucket
    marker_date = datetime.strptime(out.warren_signal_markers[0].time, "%Y-%m-%d").date()
    assert marker_date <= first_fire.date()


def test_zones_not_tracked(monkeypatch):
    df = _daily_df(300)
    _patch_bars(monkeypatch, df)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    out = asyncio.run(chart_data.get_chart_data("NOTTRACKED", "D_1Y"))

    assert out.zones_available is False
    assert out.zones == []


def test_zones_within_visible_window_included_outside_excluded(monkeypatch):
    df = _daily_df(600)
    _patch_bars(monkeypatch, df)

    today = pd.Timestamp.today().normalize()
    within = (today - pd.Timedelta(days=300)).strftime("%Y-%m-%d")  # inside D_1Y's 365-day window
    outside = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")  # older than the window

    support = [_zone_out(90.0, within), _zone_out(80.0, outside)]
    resistance = [_zone_out(110.0, within)]
    lp = LiquidityZonesOut(daily=_lp_out(support=support, resistance=resistance), weekly=None)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert out.zones_available is True
    got = {(z.side, z.price) for z in out.zones}
    assert got == {("support", 90.0), ("resistance", 110.0)}  # the outside-window support zone is dropped


def test_broken_zone_within_window_is_included_with_broken_flag_set(monkeypatch):
    df = _daily_df(600)
    _patch_bars(monkeypatch, df)

    today = pd.Timestamp.today().normalize()
    within = (today - pd.Timedelta(days=300)).strftime("%Y-%m-%d")  # inside D_1Y's 365-day window
    breached_at = (today - pd.Timedelta(days=100)).strftime("%Y-%m-%d")
    outside = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")  # older than the window

    lp = LiquidityZonesOut(
        daily=_lp_out(
            support=[],
            resistance=[],
            broken_support=_broken_zone_out(85.0, within, breached_at),
            broken_resistance=_broken_zone_out(115.0, outside, breached_at),
        ),
        weekly=None,
    )

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    # broken_support (formed within the visible window) shows up with
    # broken=True; broken_resistance (formed before the window) is dropped
    # entirely -- same "no bar to anchor against" rule active zones use.
    assert len(out.zones) == 1
    zone = out.zones[0]
    assert (zone.side, zone.price, zone.broken) == ("support", 85.0, True)


def test_no_broken_zone_when_none_currently_qualifies(monkeypatch):
    df = _daily_df(600)
    _patch_bars(monkeypatch, df)

    within = (pd.Timestamp.today().normalize() - pd.Timedelta(days=300)).strftime("%Y-%m-%d")
    lp = LiquidityZonesOut(daily=_lp_out(support=[_zone_out(90.0, within)], resistance=[]), weekly=None)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "D_1Y"))

    assert all(not z.broken for z in out.zones)


def test_zones_use_weekly_read_for_w4y_range_not_daily(monkeypatch):
    # ~9y of daily bars, matching the existing W_4Y resample test's own
    # fixture size -- enough warm-up + 4y visible window once resampled.
    df = _daily_df(365 * 9)
    _patch_bars(monkeypatch, df)

    recent = (pd.Timestamp.today().normalize() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    daily_read = _lp_out(support=[_zone_out(90.0, recent)], resistance=[])
    weekly_read = _lp_out(support=[], resistance=[_zone_out(120.0, recent)])
    lp = LiquidityZonesOut(daily=daily_read, weekly=weekly_read)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("TRACKED", "W_4Y"))

    # Only the weekly read's zone shows up -- the daily read's own zone
    # (90.0/support) is never consulted for a W_4Y request.
    assert [(z.side, z.price) for z in out.zones] == [("resistance", 120.0)]


def test_zones_absent_when_bars_empty(monkeypatch):
    _patch_bars(monkeypatch, pd.DataFrame())

    recent = (pd.Timestamp.today().normalize() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    lp = LiquidityZonesOut(daily=_lp_out(support=[_zone_out(90.0, recent)], resistance=[]), weekly=None)

    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", lambda ticker: lp)

    out = asyncio.run(chart_data.get_chart_data("BADTICKER", "D_1Y"))

    # zones_available still reflects the real (independent) cache-only
    # read, but the zones list itself is empty -- no chart to anchor
    # price lines onto, same convention entry_signal_markers uses here.
    assert out.chart_available is False
    assert out.zones_available is True
    assert out.zones == []


# ---------------------------------------------------------------------------
# Earnings / dividend event markers
# ---------------------------------------------------------------------------


def _patch_events(monkeypatch, events: ChartEvents) -> None:
    async def fake_fetch(ticker):
        return events

    monkeypatch.setattr(chart_data, "fetch_chart_events", fake_fetch)


def _run_chart(monkeypatch, range_key: str = "D_1Y", *, n: int = 600, events: ChartEvents):
    _patch_bars(monkeypatch, _daily_df(n))
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    _patch_events(monkeypatch, events)
    return asyncio.run(chart_data.get_chart_data("TEST", range_key))


def _days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)


def test_event_markers_default_to_empty_and_source_none(monkeypatch):
    # The autouse stub: no events at all reads as "nothing fetched".
    out = _run_chart(monkeypatch, events=ChartEvents())

    assert out.earnings_markers == []
    assert out.dividend_markers == []
    assert out.events_source is None


def test_earnings_marker_lands_on_the_report_days_bar_and_carries_eps(monkeypatch):
    # Anchor on a real bar date so the assertion doesn't depend on which
    # weekday "N days ago" happens to be.
    df = _daily_df(600)
    report = df.index[-40].date()
    events = ChartEvents(earnings=[EarningsEvent(report, 1.25, 1.10)], source="fmp")

    out = _run_chart(monkeypatch, events=events)

    assert out.events_source == "fmp"
    assert len(out.earnings_markers) == 1
    m = out.earnings_markers[0]
    assert m.time == report.isoformat()
    assert m.event_date == report.isoformat()
    assert (m.eps_actual, m.eps_estimated) == (1.25, 1.10)


def test_weekend_event_snaps_back_to_the_prior_trading_bar_but_keeps_its_own_date(monkeypatch):
    df = _daily_df(600)
    friday = next(ts.date() for ts in reversed(df.index[:-10]) if ts.weekday() == 4)
    saturday = friday + timedelta(days=1)
    events = ChartEvents(dividends=[DividendEvent(saturday, 0.5)], source="fmp")

    out = _run_chart(monkeypatch, events=events)

    assert len(out.dividend_markers) == 1
    assert out.dividend_markers[0].time == friday.isoformat()
    assert out.dividend_markers[0].event_date == saturday.isoformat()


def test_events_outside_the_visible_window_are_dropped(monkeypatch):
    # D_6M shows ~182 days: a report 300 days ago sits in the warm-up-inclusive
    # fetch history but has no visible bar to attach to.
    events = ChartEvents(
        earnings=[EarningsEvent(_days_ago(300), 1.0, 1.0)],
        dividends=[DividendEvent(_days_ago(300), 0.3)],
        source="fmp",
    )

    out_6m = _run_chart(monkeypatch, "D_6M", events=events)
    out_1y = _run_chart(monkeypatch, "D_1Y", events=events)

    assert out_6m.earnings_markers == [] and out_6m.dividend_markers == []
    assert len(out_1y.earnings_markers) == 1 and len(out_1y.dividend_markers) == 1


def test_future_scheduled_events_never_snap_onto_the_last_bar(monkeypatch):
    # FMP lists the next scheduled earnings date and declared-ahead ex-dates.
    # _marker_bar_time alone would snap these onto the newest bar, showing a
    # scheduled event as if it had happened -- the future-date guard prevents
    # that, in both the daily and weekly views.
    events = ChartEvents(
        earnings=[EarningsEvent(date.today() + timedelta(days=20), 2.0, 1.9)],
        dividends=[DividendEvent(date.today() + timedelta(days=20), 0.4)],
        source="fmp",
    )

    for range_key in ("D_1Y", "W_4Y"):
        out = _run_chart(monkeypatch, range_key, n=1200, events=events)
        assert out.earnings_markers == [], range_key
        assert out.dividend_markers == [], range_key


def test_weekly_view_buckets_events_onto_the_monday_week_bar(monkeypatch):
    df = _daily_df(1200)
    # A Wednesday well inside the 4y window.
    wednesday = next(ts.date() for ts in reversed(df.index[:-60]) if ts.weekday() == 2)
    monday = wednesday - timedelta(days=2)
    events = ChartEvents(earnings=[EarningsEvent(wednesday, 0.8, 0.7)], source="fmp")

    out = _run_chart(monkeypatch, "W_4Y", n=1200, events=events)

    assert out.timeframe == "weekly"
    assert len(out.earnings_markers) == 1
    assert out.earnings_markers[0].time == monday.isoformat()
    assert out.earnings_markers[0].event_date == wednesday.isoformat()  # tooltip shows the real report date


def test_event_in_the_current_partial_week_lands_on_the_current_week_bar(monkeypatch):
    # The weekly view's last bar is indexed by this week's Monday; an event
    # from earlier this week belongs to it, and the cutoff (that week's
    # Sunday, capped at today) must not reject it.
    df = _daily_df(1200)
    last_trading_day = df.index[-1].date()
    events = ChartEvents(dividends=[DividendEvent(last_trading_day, 0.25)], source="fmp")

    out = _run_chart(monkeypatch, "W_4Y", n=1200, events=events)

    assert len(out.dividend_markers) == 1
    marker_monday = date.fromisoformat(out.dividend_markers[0].time)
    assert marker_monday.weekday() == 0
    assert 0 <= (last_trading_day - marker_monday).days <= 6


def test_dividends_in_one_bar_sum_and_report_the_earlier_ex_date(monkeypatch):
    df = _daily_df(1200)
    monday = next(ts.date() for ts in reversed(df.index[:-60]) if ts.weekday() == 0)
    events = ChartEvents(
        dividends=[DividendEvent(monday + timedelta(days=3), 1.0), DividendEvent(monday + timedelta(days=1), 0.25)], source="fmp"
    )

    out = _run_chart(monkeypatch, "W_4Y", n=1200, events=events)

    assert len(out.dividend_markers) == 1
    m = out.dividend_markers[0]
    assert m.amount == 1.25
    assert m.event_date == (monday + timedelta(days=1)).isoformat()


def test_duplicate_earnings_rows_in_one_bar_keep_the_first(monkeypatch):
    df = _daily_df(600)
    day = df.index[-30].date()
    events = ChartEvents(earnings=[EarningsEvent(day, 1.0, 0.9), EarningsEvent(day, 5.0, 0.9)], source="fmp")

    out = _run_chart(monkeypatch, events=events)

    assert len(out.earnings_markers) == 1
    assert out.earnings_markers[0].eps_actual == 1.0


def test_no_bars_still_reports_events_source_and_no_markers(monkeypatch):
    _patch_bars(monkeypatch, pd.DataFrame())
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    _patch_events(monkeypatch, ChartEvents(earnings=[EarningsEvent(_days_ago(30), 1.0, 1.0)], source="fmp"))

    out = asyncio.run(chart_data.get_chart_data("BADTICKER", "D_1Y"))

    assert out.chart_available is False
    assert out.earnings_markers == [] and out.dividend_markers == []


def test_events_are_fetched_concurrently_with_the_bars(monkeypatch):
    # Deterministic, not timing-based: each side blocks until the OTHER has
    # started. If get_chart_data awaited them one after the other, the first
    # would wait forever for a second that never begins (wait_for turns that
    # into a failure instead of a hang).
    events_started, bars_started = asyncio.Event(), asyncio.Event()

    async def events_waiting_for_bars(ticker):
        events_started.set()
        await asyncio.wait_for(bars_started.wait(), timeout=2)
        return ChartEvents()

    rows = _fmp_rows(300)

    async def bars_waiting_for_events(ticker, from_date, to_date, group="daily_prices"):
        bars_started.set()
        await asyncio.wait_for(events_started.wait(), timeout=2)
        return rows

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", bars_waiting_for_events)
    monkeypatch.setattr(chart_data, "get_entry_signal_data", _no_entry_signal)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    monkeypatch.setattr(chart_data, "fetch_chart_events", events_waiting_for_bars)

    out = asyncio.run(chart_data.get_chart_data("TEST", "D_1Y"))

    assert out.chart_available is True


def test_w4y_weinstein_overlay_matches_engine_and_uses_live_params(monkeypatch, _fresh_chart_data_engine):
    from sqlmodel import Session

    from analysis.trend_structure.weinstein import WeinsteinParams, compute_stage_series
    from helpers.weinstein_config import update_weinstein_settings

    df = _daily_df(365 * 9)
    _patch_bars(monkeypatch, df)
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)

    with Session(_fresh_chart_data_engine) as session:
        update_weinstein_settings(session, **{**WeinsteinParams().__dict__, "ma_type": "SMA", "ma_length": 20})

    out = asyncio.run(chart_data.get_chart_data("TEST", "W_4Y"))

    assert out.weinstein_ma_label == "SMA20"
    weekly = resample_to_weekly(df.rename(columns=str.lower))
    expected = compute_stage_series(weekly["close"], WeinsteinParams(ma_type="SMA", ma_length=20))
    visible_times = {b.time for b in out.bars}
    exp_stage = {i.strftime("%Y-%m-%d"): s for i, s in expected["stage"].items() if isinstance(s, str) and i.strftime("%Y-%m-%d") in visible_times}
    assert exp_stage and {p.time: p.stage for p in out.weinstein_stages} == exp_stage
    exp_ma = {i.strftime("%Y-%m-%d"): v for i, v in expected["ma"].dropna().items() if i.strftime("%Y-%m-%d") in visible_times}
    assert {p.time: p.value for p in out.weinstein_ma} == pytest.approx(exp_ma)


def test_daily_ranges_have_no_weinstein_overlay(monkeypatch):
    _patch_bars(monkeypatch, _daily_df(400))
    monkeypatch.setattr(chart_data, "get_liquidity_zone_data", _no_zones)
    out = asyncio.run(chart_data.get_chart_data("TEST", "D_1Y"))
    assert out.weinstein_stages == [] and out.weinstein_ma == [] and out.weinstein_ma_label is None
