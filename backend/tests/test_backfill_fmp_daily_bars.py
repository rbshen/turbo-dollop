import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.daily_bar_sources as daily_bar_sources
import clients.shared_bars_cache as shared_bars_cache
import pipeline.backfills.backfill_fmp_daily_bars as backfill
from clients.daily_bar_sources import FMPDailySource
from core.models import SharedBarsCache, TickerScore

TODAY = date(2026, 9, 23)


class FakeFMP:
    def __init__(self, series, failing=()):
        self.series, self.failing = series, set(failing)

    async def get_historical_price_eod(self, ticker, from_date, to_date, group="daily_prices"):
        if ticker in self.failing:
            raise httpx.ConnectError("boom")
        return [
            {"date": d.isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 10}
            for d, c in sorted(self.series.get(ticker, {}).items(), reverse=True)
        ]


def _series(start, n, base=100.0, scale=1.0):
    return {start + timedelta(days=i): (base + i) * scale for i in range(n)}


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (backfill, shared_bars_cache, daily_bar_sources):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(backfill, "init_db", lambda: None)
    monkeypatch.setattr(backfill, "LOG_PATH", tmp_path / "bf.log")
    monkeypatch.setattr(backfill, "_eastern_today", lambda: TODAY)
    monkeypatch.setattr(daily_bar_sources, "_completed_session", lambda: TODAY)
    return engine


def _seed(engine, ticker, series, fetched=datetime(2026, 9, 1)):
    with Session(engine) as session:
        for d, c in series.items():
            session.add(SharedBarsCache(ticker=ticker, interval="1d", bar_time=datetime.combine(d, datetime.min.time()),
                                        open=c, high=c, low=c, close=c, volume=1, fetched_at=fetched))
        session.commit()


def _rows(engine, ticker):
    with Session(engine) as session:
        return {r.bar_time.date(): r.close for r in session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == ticker)).all()}


def _run(monkeypatch, fmp, tickers, **kwargs):
    monkeypatch.setattr(backfill, "FMPDailySource", lambda: FMPDailySource(client=fmp))
    return asyncio.run(backfill.main(tickers, **kwargs))


def test_dry_run_writes_nothing_but_reports_the_comparison(env, monkeypatch):
    old = _series(TODAY - timedelta(days=99), 100)
    _seed(env, "AAPL", old)
    summary = _run(monkeypatch, FakeFMP({"AAPL": _series(TODAY - timedelta(days=99), 100, scale=0.9)}), ["AAPL"], dry_run=True)
    assert summary["served_by_fmp"] == 1 and summary["rows_written"] == 0
    assert summary["tickers_with_days_off_gt_1pct"] == ["AAPL"]  # a 10% restatement (spin-off shaped)
    assert _rows(env, "AAPL") == old


def test_real_run_replaces_a_stitched_history_and_reports_shrink(env, monkeypatch):
    stitched = _series(TODAY - timedelta(days=499), 500, base=10.0)  # an old ticker's rows under a reused symbol
    _seed(env, "SPCX", stitched)
    fresh = _series(TODAY - timedelta(days=70), 71, base=160.0)
    summary = _run(monkeypatch, FakeFMP({"SPCX": fresh}), ["SPCX"])
    assert summary["shrunk"] == ["SPCX"] and summary["rows_written"] == 71
    assert set(_rows(env, "SPCX")) == set(fresh)  # every old date gone, not upserted over


def test_a_ticker_fmp_cannot_serve_keeps_its_rows_and_delisted_is_skipped(env, monkeypatch):
    _seed(env, "MSFT", _series(TODAY - timedelta(days=99), 100))
    _seed(env, "AVB", _series(TODAY - timedelta(days=99), 100))
    with Session(env) as session:
        session.add(TickerScore(ticker="AVB", computed_at=datetime(2026, 9, 24), delisted_at=datetime(2026, 9, 24)))
        session.commit()
    before = _rows(env, "MSFT")
    summary = _run(monkeypatch, FakeFMP({"AVB": _series(TODAY - timedelta(days=99), 100, scale=2)}, failing={"MSFT"}), ["MSFT", "AVB"])
    assert summary["kept_not_served"] == ["MSFT"] and summary["delisted_skipped"] == ["AVB"]
    assert _rows(env, "AVB")[TODAY] == _series(TODAY - timedelta(days=99), 100)[TODAY]


def test_refuses_to_run_while_daily_prices_is_off(env, monkeypatch):
    import core.data_groups as dg

    dg.set_group_enabled("daily_prices", False)
    with pytest.raises(RuntimeError):
        _run(monkeypatch, FakeFMP({}), ["AAPL"])


# --- P3: non-US scope ------------------------------------------------------------------------------


def _weekday_series(n, end=TODAY, base=100.0, scale=1.0):
    out, d = {}, end
    while len(out) < n:
        if d.weekday() < 5:
            out[d] = (base + len(out)) * scale
        d -= timedelta(days=1)
    return out


class FakeIntlFMP(FakeFMP):
    """Adds a phantom Sunday bar and a flat copy to whatever it serves."""

    async def get_historical_price_eod(self, ticker, from_date, to_date, group="daily_prices"):
        self.groups = getattr(self, "groups", []) + [group]
        rows = await super().get_historical_price_eod(ticker, from_date, to_date, group)
        newest_weekday = max(r["date"] for r in rows)
        sunday = (date.fromisoformat(newest_weekday) - timedelta(days=date.fromisoformat(newest_weekday).weekday() + 1))
        rows.append({"date": sunday.isoformat(), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 5})
        return rows


def _run_intl(monkeypatch, fmp, tickers, **kwargs):
    monkeypatch.setattr(backfill, "FMPDailySource", lambda **kw: FMPDailySource(client=fmp, **kw))
    return asyncio.run(backfill.main(tickers, scope="non-us", **kwargs))


def test_non_us_scope_uses_the_intl_group_drops_phantoms_and_replaces(env, monkeypatch):
    series = _weekday_series(60)
    _seed(env, "0005.HK", {d: c for d, c in list(series.items())[:30]})  # a narrower cache, same closes
    fmp = FakeIntlFMP({"0005.HK": series})
    summary = _run_intl(monkeypatch, fmp, ["0005.HK"])
    assert fmp.groups == ["daily_prices_intl"] and summary["scope"] == "non-us"
    assert summary["phantom_bars_dropped"] == {"0005.HK": 1} and summary["parity_gate_failures"] == {}
    rows = _rows(env, "0005.HK")
    assert set(rows) == set(series) and all(d.weekday() < 5 for d in rows)


def test_non_us_scope_leaves_us_tickers_alone_and_us_scope_leaves_non_us_alone(env, monkeypatch):
    _seed(env, "AAPL", _weekday_series(40))
    _seed(env, "0005.HK", _weekday_series(40))
    fmp = FakeIntlFMP({"AAPL": _weekday_series(40, scale=2), "0005.HK": _weekday_series(40)})
    summary = _run_intl(monkeypatch, fmp, ["AAPL", "0005.HK"], dry_run=True)
    assert summary["served_by_fmp"] == 1 and summary["non_us_routed"] == 1 and summary["us_routed"] == 1
    monkeypatch.setattr(backfill, "FMPDailySource", lambda **kw: FMPDailySource(client=FakeFMP({"AAPL": _weekday_series(40)}), **kw))
    summary = asyncio.run(backfill.main(["AAPL", "0005.HK"], dry_run=True))  # default scope: us
    assert summary["served_by_fmp"] == 1 and summary["scope"] == "us"


def test_parity_gate_failure_writes_nothing(env, monkeypatch):
    old = _weekday_series(60)
    _seed(env, "0728.HK", old)
    before = _rows(env, "0728.HK")
    fmp = FakeIntlFMP({"0728.HK": _weekday_series(60, scale=1.2)})  # every close 20% off
    with pytest.raises(backfill.ParityGateError):
        _run_intl(monkeypatch, fmp, ["0728.HK"])
    assert _rows(env, "0728.HK") == before
    # a dry run reports the failure instead of raising
    summary = _run_intl(monkeypatch, fmp, ["0728.HK"], dry_run=True)
    assert "0728.HK" in summary["parity_gate_failures"] and summary["rows_written"] == 0


def test_gate_reports_each_date_off_by_more_than_the_tolerance(env, monkeypatch, tmp_path):
    series = _weekday_series(200)
    _seed(env, "0941.HK", series)
    bad_day = sorted(series)[100]
    served = dict(series)
    served[bad_day] = series[bad_day] * 1.02
    report = tmp_path / "r.json"
    summary = _run_intl(monkeypatch, FakeIntlFMP({"0941.HK": served}), ["0941.HK"], dry_run=True, report_path=report)
    import json as _json

    per = _json.loads(report.read_text())["per_ticker"]["0941.HK"]
    assert list(per["dates_off_gt_0.5pct"]) == [str(bad_day)]
    assert per["within_0.5pct_pct"] >= 99.0 and summary["parity_gate_failures"] == {}


def test_non_us_scope_refuses_while_the_intl_group_is_off(env, monkeypatch):
    import core.data_groups as dg

    dg.set_group_enabled("daily_prices_intl", False)
    with pytest.raises(RuntimeError):
        _run_intl(monkeypatch, FakeFMP({}), ["0005.HK"])
