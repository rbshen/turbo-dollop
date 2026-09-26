"""clients/long_history_bars.py -- the on-demand 10y FMP store (P3.5). Fake FMP client, fresh
in-memory engine (also patched onto daily_bar_sources for the exchange lookup and
shared_bars_cache for the isolation tests)."""

import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.daily_bar_sources as daily_bar_sources
import clients.long_history_bars as lhb
import clients.shared_bars_cache as shared_bars_cache
import core.data_groups as dg
from clients.long_history_bars import LONG_HISTORY_YEARS, get_long_history
from core.models import FundamentalsCache, LongHistoryBars, SharedBarsCache

REF = datetime(2026, 9, 25, 3, 10, tzinfo=timezone.utc)  # 2026-09-24 23:10 ET: most recent completed session = Thu 09-24
SESSION = date(2026, 9, 24)


def _weekdays(n: int, end: date = SESSION) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class FakeFMP:
    """Serves `series` ({ticker: {date: close}}) like the real endpoint: newest first, honours `from`."""

    def __init__(self, series, fail=(), delay=0.0):
        self.series, self.fail, self.delay = series, set(fail), delay
        self.calls: list[tuple[str, str, str]] = []  # (ticker, from, group)

    async def get_historical_price_eod(self, ticker, from_date, to_date, group="daily_prices"):
        self.calls.append((ticker, from_date, group))
        if self.delay:
            await asyncio.sleep(self.delay)
        if ticker in self.fail:
            raise httpx.ConnectError("boom")
        return [
            {"symbol": ticker, "date": d.isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000 + i}
            for i, (d, c) in enumerate(sorted(self.series.get(ticker, {}).items(), reverse=True))
            if from_date <= d.isoformat() <= to_date
        ]


def _series(n: int, end: date = SESSION, base: float = 100.0, scale: float = 1.0) -> dict[date, float]:
    return {d: (base + i) * scale for i, d in enumerate(_weekdays(n, end))}


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (lhb, daily_bar_sources, shared_bars_cache):
        monkeypatch.setattr(module, "engine", engine)
    return engine


def _stored(engine, ticker):
    with Session(engine) as session:
        return {r.bar_time.date(): r.close for r in session.exec(select(LongHistoryBars).where(LongHistoryBars.ticker == ticker)).all()}


def _seed(engine, ticker, series, fetched_at=datetime(2026, 9, 25, 5, 0)):  # after the 09-24 close
    with Session(engine) as session:
        for d, c in series.items():
            session.add(LongHistoryBars(ticker=ticker, bar_time=datetime.combine(d, datetime.min.time()), open=c, high=c, low=c, close=c, volume=1, fetched_at=fetched_at))
        session.commit()


def _seed_profile(engine, ticker, exchange):
    import json

    with Session(engine) as session:
        session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", raw_json=json.dumps([{"exchange": exchange}]), fetched_at=datetime.now()))
        session.commit()


def _run(coro):
    return asyncio.run(coro)


def test_cold_fetch_pulls_ten_years_once_writes_and_serves(db):
    fmp = FakeFMP({"KO": _series(2700)})
    frame = _run(get_long_history("KO", reference=REF, client=fmp))
    assert [c[2] for c in fmp.calls] == ["daily_prices_long"] and len(fmp.calls) == 1
    start = (date(2026, 9, 24) - timedelta(days=365 * LONG_HISTORY_YEARS + 2)).isoformat()
    assert fmp.calls[0][1] == start
    assert len(frame) == len(_stored(db, "KO")) and frame.index.max() == pd.Timestamp(SESSION)
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame.index.min() >= pd.Timestamp(start)


def test_warm_fresh_read_makes_no_fmp_call(db):
    fmp = FakeFMP({"KO": _series(2700)})
    _run(get_long_history("KO", reference=REF, client=fmp))
    fmp.calls.clear()
    frame = _run(get_long_history("KO", reference=REF, client=fmp))
    assert fmp.calls == [] and frame.index.max() == pd.Timestamp(SESSION)


def test_stale_row_gets_an_incremental_top_up_not_a_full_refetch(db):
    old_end = date(2026, 9, 21)
    _seed(db, "KO", _series(500, end=old_end))
    n_before = len(_stored(db, "KO"))
    served = {**_series(500, end=old_end), **{d: 200.0 + i for i, d in enumerate(_weekdays(3, SESSION))}}  # same closes on shared dates + 3 new
    fmp = FakeFMP({"KO": served})
    frame = _run(get_long_history("KO", reference=REF, client=fmp))
    assert len(fmp.calls) == 1 and fmp.calls[0][1] == (old_end - timedelta(days=7)).isoformat()
    assert frame.index.max() == pd.Timestamp(SESSION) and len(_stored(db, "KO")) > n_before
    assert len(_stored(db, "KO")) == len(frame)


def test_restated_history_refetches_the_full_window_and_replaces_the_row(db):
    old_end = date(2026, 9, 21)
    _seed(db, "T", _series(400, end=old_end))
    restated = _series(3000, end=SESSION, scale=0.8)  # a spin-off: every close moved 20%
    fmp = FakeFMP({"T": restated})
    frame = _run(get_long_history("T", reference=REF, client=fmp))
    assert len(fmp.calls) == 2  # overlapping top-up, then the full window
    assert fmp.calls[1][1] < fmp.calls[0][1]
    stored = _stored(db, "T")
    assert len(stored) == len(frame) and all(abs(stored[d] - restated[d]) < 1e-9 for d in stored)  # replaced, not upserted over


def test_a_provisional_last_bar_written_before_the_close_is_refetched(db):
    # the last bar is the completed session's, but it was written well before that session's close
    _seed(db, "KO", _series(300), fetched_at=datetime(2026, 9, 24, 9, 0))
    fmp = FakeFMP({"KO": _series(300)})
    _run(get_long_history("KO", reference=REF, client=fmp))
    assert len(fmp.calls) == 1


def test_group_off_serves_an_existing_row_as_is_and_never_calls_fmp(db):
    _seed(db, "KO", _series(300, end=date(2026, 9, 21)))
    dg.set_group_enabled("daily_prices_long", False)
    fmp = FakeFMP({"KO": _series(300)})
    frame = _run(get_long_history("KO", reference=REF, client=fmp))
    assert fmp.calls == [] and frame.index.max() == pd.Timestamp(date(2026, 9, 21))
    assert len(_stored(db, "KO")) == 300  # never wiped


def test_group_off_without_a_row_falls_through(db):
    dg.set_group_enabled("daily_prices_long", False)
    fmp = FakeFMP({"KO": _series(300)})
    assert _run(get_long_history("KO", reference=REF, client=fmp)) is None
    assert fmp.calls == [] and _stored(db, "KO") == {}


def test_master_switch_and_plan_restriction_also_mean_cached_only(db):
    fmp = FakeFMP({"KO": _series(300)})
    dg.set_master(False)
    assert _run(get_long_history("KO", reference=REF, client=fmp)) is None
    dg.set_master(True)
    dg.mark_restricted("daily_prices_long", "simulated 402")
    assert _run(get_long_history("KO", reference=REF, client=fmp)) is None and fmp.calls == []


def test_fmp_error_or_empty_on_a_cold_ticker_falls_through_without_writing(db):
    assert _run(get_long_history("KO", reference=REF, client=FakeFMP({}, fail={"KO"}))) is None
    assert _run(get_long_history("KO", reference=REF, client=FakeFMP({"KO": {}}))) is None
    assert _stored(db, "KO") == {}


def test_fmp_error_on_a_warm_stale_row_serves_the_existing_row(db):
    _seed(db, "KO", _series(300, end=date(2026, 9, 21)))
    frame = _run(get_long_history("KO", reference=REF, client=FakeFMP({}, fail={"KO"})))
    assert len(frame) == 300 and len(_stored(db, "KO")) == 300


def test_concurrent_first_opens_make_exactly_one_fmp_call(db):
    fmp = FakeFMP({"KO": _series(2700)}, delay=0.05)

    async def go():
        return await asyncio.gather(*(get_long_history("KO", reference=REF, client=fmp) for _ in range(6)))

    frames = _run(go())
    assert len(fmp.calls) == 1
    assert all(len(f) == len(frames[0]) for f in frames)


def test_single_flight_is_per_ticker_and_survives_a_new_event_loop_each_run(db):
    fmp = FakeFMP({"KO": _series(300), "PEP": _series(300)}, delay=0.02)

    async def go():
        return await asyncio.gather(*(get_long_history(t, reference=REF, client=fmp) for t in ("KO", "PEP", "KO", "PEP")))

    _run(go())
    assert sorted(c[0] for c in fmp.calls) == ["KO", "PEP"]
    fmp.calls.clear()
    _run(go())  # a second loop: no cross-loop lock error, both warm
    assert fmp.calls == []


def test_a_non_us_symbol_uses_the_long_group_like_any_other_and_is_not_filtered(db):
    series = _series(400)
    sunday = SESSION - timedelta(days=SESSION.weekday() + 1)  # a Sunday inside the window
    series[sunday] = 1.0
    fmp = FakeFMP({"0005.HK": series})
    frame = _run(get_long_history("0005.HK", reference=REF, client=fmp))
    assert [c[2] for c in fmp.calls] == ["daily_prices_long"]
    assert pd.Timestamp(sunday) in frame.index  # no phantom filter any more


def test_a_partial_bar_dated_after_the_last_completed_session_is_never_stored(db):
    series = _series(300)
    series[SESSION + timedelta(days=1)] = 999.0  # Fri 09-25, mid-session bar
    frame = _run(get_long_history("KO", reference=REF, client=FakeFMP({"KO": series})))
    assert frame.index.max() == pd.Timestamp(SESSION) and date(2026, 9, 25) not in _stored(db, "KO")


# --- isolation from the nightly shared cache ----------------------------------------------------


def test_prune_old_bars_leaves_the_long_history_table_untouched(db):
    _seed(db, "KO", {d: 50.0 for d in _weekdays(2600)})  # ~10y, far past the 6y 1d retention
    before = _stored(db, "KO")
    with Session(db) as session:  # and a SharedBarsCache row past the window WOULD be pruned
        session.add(SharedBarsCache(ticker="KO", interval="1d", bar_time=datetime(2015, 1, 5), open=1, high=1, low=1, close=1, volume=1, fetched_at=datetime.now()))
        session.commit()
    deleted = shared_bars_cache.prune_old_bars(reference=REF)
    assert deleted["1d"] == 1
    assert _stored(db, "KO") == before


def test_a_long_history_row_does_not_change_what_the_nightly_job_fetches(db, monkeypatch):
    """The nightly fetch decision reads SharedBarsCache only: a 10y row beside it must not widen
    the ticker's requested lookback (no _preserved_lookback_days ratchet) or make it look covered."""
    _seed(db, "KO", {d: 50.0 for d in _weekdays(2600)})
    seen = {}

    class Src:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, fallback_tickers=None, replace_tickers=None, full_refresh=False):
            seen.update(tickers_with_days)
            return {}

    monkeypatch.setattr(shared_bars_cache, "get_daily_bar_source", lambda non_us=False: Src())
    asyncio.run(shared_bars_cache.get_or_fetch_bars_batch(["KO"], "1d", lookback_days=730, reference=REF))
    assert seen == {"KO": 730}
    assert _stored(db, "KO")  # and the nightly path did not touch the long table
