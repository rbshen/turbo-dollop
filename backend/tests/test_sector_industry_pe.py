"""Sector / industry average P/E data layer (docs/specs/sector-industry-pe.md): group mapping, upsert-only writes and
the unique key, backfill idempotency / resumability / empty handling, and the nightly job's gating."""

import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

import core.data_groups as dg
import data.sector_industry_pe_data as pe_data
import pipeline.nightly_sector_industry_pe as job
from core.cron_health import CronRunContext
from core.models import SectorIndustryPe

END = date(2026, 10, 8)
START = date(2021, 10, 9)
ENDPOINTS = ("/sector-pe-snapshot", "/industry-pe-snapshot", "/historical-sector-pe", "/historical-industry-pe")


@pytest.fixture
def engine(monkeypatch, tmp_path):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(pe_data, "engine", eng)
    monkeypatch.setattr(job, "LOG_PATH", tmp_path / "x.log")
    monkeypatch.setattr(job, "init_db", lambda: None)
    monkeypatch.setattr(pe_data, "_most_recent_completed_trading_date", lambda: END)
    return eng


def _row(kind, name, exchange, day, pe):
    return {"date": day, kind: name, "exchange": exchange, "pe": pe}


class FakeFmp:
    """Stands in for the FMP client. `sectors`/`industries`: exchange -> names on the snapshot. `series`: (kind, name,
    exchange) -> rows; a missing key answers []. `fail`: set of (kind, name, exchange) that raise."""

    def __init__(self, sectors, industries, series=None, fail=()):
        self.sectors, self.industries, self.series, self.fail = sectors, industries, series or {}, set(fail)
        self.calls: list[tuple] = []

    async def get_sector_pe_snapshot(self, on_date, exchange):
        self.calls.append(("snap", "sector", exchange, on_date))
        if ("sector", "*", exchange) in self.fail:
            raise RuntimeError("boom")
        return [_row("sector", n, exchange, on_date, 20.0) for n in self.sectors.get(exchange, [])]

    async def get_industry_pe_snapshot(self, on_date, exchange):
        self.calls.append(("snap", "industry", exchange, on_date))
        if ("industry", "*", exchange) in self.fail:
            raise RuntimeError("boom")
        return [_row("industry", n, exchange, on_date, 15.0) for n in self.industries.get(exchange, [])]

    async def _hist(self, kind, name, exchange, from_date, to_date):
        self.calls.append(("hist", kind, name, exchange, from_date, to_date))
        if (kind, name, exchange) in self.fail:
            raise RuntimeError("boom")
        return self.series.get((kind, name, exchange), [])

    async def get_historical_sector_pe(self, name, exchange, from_date, to_date):
        return await self._hist("sector", name, exchange, from_date, to_date)

    async def get_historical_industry_pe(self, name, exchange, from_date, to_date):
        return await self._hist("industry", name, exchange, from_date, to_date)


def _install(monkeypatch, fake):
    monkeypatch.setattr(pe_data, "fmp_client", fake)
    return fake


def _all(engine):
    with Session(engine) as s:
        return s.exec(select(SectorIndustryPe)).all()


# --- group mapping ---------------------------------------------------------


def test_all_four_endpoints_map_to_the_group_and_it_is_registered():
    for endpoint in ENDPOINTS:
        assert dg.ENDPOINT_GROUP[endpoint] == "sector_industry_pe"
    meta = dg.GROUPS["sector_industry_pe"]
    assert meta.live and meta.default_enabled and meta.default_tier == "Starter"
    assert dg.PROBE_ENDPOINTS["sector_industry_pe"][0] in ENDPOINTS


def test_client_methods_pass_exchange_and_explicit_dates(monkeypatch):
    from clients.fmp_client import FMPClient

    seen = []

    async def fake_get(self, endpoint, params=None, group=None):
        seen.append((endpoint, params))
        return []

    monkeypatch.setattr(FMPClient, "get", fake_get)
    c = FMPClient(api_key="x")
    asyncio.run(c.get_sector_pe_snapshot("2026-10-08", "NYSE"))
    asyncio.run(c.get_industry_pe_snapshot("2026-10-08", "AMEX"))
    asyncio.run(c.get_historical_sector_pe("Technology", "NASDAQ", "2021-10-09", "2026-10-08"))
    asyncio.run(c.get_historical_industry_pe("Software - Application", "NYSE", "2021-10-09", "2026-10-08"))
    assert [e for e, _ in seen] == list(ENDPOINTS[:2]) + [ENDPOINTS[2], ENDPOINTS[3]]
    assert all(p["exchange"] in pe_data.EXCHANGES for _, p in seen)
    assert seen[2][1]["from"] == "2021-10-09" and seen[3][1]["to"] == "2026-10-08"


# --- parsing, upsert, uniqueness -------------------------------------------


def test_parse_rows_drops_malformed_rows_and_other_exchanges():
    body = [
        _row("sector", "Technology", "NYSE", "2026-10-08", 30.5),
        _row("sector", "Technology", "NASDAQ", "2026-10-08", 99.0),  # other exchange
        {"date": "2026-10-08", "sector": "Energy", "exchange": "NYSE", "pe": None},
        {"date": "bad", "sector": "Energy", "exchange": "NYSE", "pe": 1.0},
        {"date": "2026-10-08", "exchange": "NYSE", "pe": 1.0},  # no name
        "junk",
    ]
    rows = pe_data.parse_rows("sector", "NYSE", body)
    assert rows == [{"kind": "sector", "name": "Technology", "exchange": "NYSE", "date": date(2026, 10, 8), "pe": 30.5}]
    assert pe_data.parse_rows("sector", "NYSE", {"error": "x"}) == [] and pe_data.parse_rows("sector", "NYSE", None) == []


def test_upsert_replaces_the_same_key_and_never_duplicates(engine):
    row = {"kind": "sector", "name": "Technology", "exchange": "NYSE", "date": END, "pe": 30.0}
    pe_data.upsert_rows([row])
    pe_data.upsert_rows([{**row, "pe": 31.5}, {**row, "date": date(2026, 10, 7), "pe": 29.0}])
    stored = {r.date: r.pe for r in _all(engine)}
    assert stored == {END: 31.5, date(2026, 10, 7): 29.0}


def test_unique_constraint_rejects_a_duplicate_key(engine):
    with Session(engine) as s:
        s.add(SectorIndustryPe(kind="industry", name="Banks - Regional", exchange="NYSE", date=END, pe=10.0))
        s.commit()
        s.add(SectorIndustryPe(kind="industry", name="Banks - Regional", exchange="NYSE", date=END, pe=11.0))
        with pytest.raises(IntegrityError):
            s.commit()
    # the same name on another exchange, or kind, is a different key
    with Session(engine) as s:
        s.add(SectorIndustryPe(kind="industry", name="Banks - Regional", exchange="NASDAQ", date=END, pe=10.0))
        s.add(SectorIndustryPe(kind="sector", name="Banks - Regional", exchange="NYSE", date=END, pe=10.0))
        s.commit()


def test_an_empty_answer_never_removes_stored_rows(engine, monkeypatch):
    pe_data.upsert_rows([{"kind": "sector", "name": "Energy", "exchange": "NYSE", "date": START, "pe": 12.0}])
    fake = _install(monkeypatch, FakeFmp({"NYSE": ["Energy"]}, {}))  # the history answer is []
    result = asyncio.run(pe_data.backfill_history(START, END, exchanges=("NYSE",), force=True))
    assert result.empty == [("sector", "Energy", "NYSE")]
    assert len(_all(engine)) == 1
    assert fake.calls


def test_get_series_returns_oldest_first_within_five_years(engine):
    today = date.today()
    recent, older = today - timedelta(days=1), today - timedelta(days=2)
    pe_data.upsert_rows(
        [
            {"kind": "sector", "name": "Energy", "exchange": "NYSE", "date": recent, "pe": 2.0},
            {"kind": "sector", "name": "Energy", "exchange": "NYSE", "date": older, "pe": 1.0},
            {"kind": "sector", "name": "Energy", "exchange": "NYSE", "date": today - timedelta(days=366 * 6), "pe": 9.0},
            {"kind": "sector", "name": "Energy", "exchange": "NASDAQ", "date": recent, "pe": 7.0},
        ]
    )
    assert pe_data.get_series("sector", "Energy", "NYSE") == [(older, 1.0), (recent, 2.0)]
    assert pe_data.get_series("industry", "Energy", "NYSE") == []


# --- backfill --------------------------------------------------------------


def _series(kind, name, exchange, first=START, last=END):
    return [_row(kind, name, exchange, first.isoformat(), 10.0), _row(kind, name, exchange, last.isoformat(), 11.0)]


def _fake_universe():
    return FakeFmp(
        {"NYSE": ["Energy"], "NASDAQ": ["Energy"]},
        {"NYSE": ["Banks - Regional", "Asset Management"], "NASDAQ": ["Banks - Regional"]},
        {
            ("sector", "Energy", "NYSE"): _series("sector", "Energy", "NYSE"),
            ("sector", "Energy", "NASDAQ"): _series("sector", "Energy", "NASDAQ"),
            ("industry", "Banks - Regional", "NYSE"): _series("industry", "Banks - Regional", "NYSE"),
            ("industry", "Banks - Regional", "NASDAQ"): _series("industry", "Banks - Regional", "NASDAQ"),
            # ("industry", "Asset Management", "NYSE") has no series: FMP answers []
        },
    )


def test_backfill_loads_every_series_and_records_nothing_for_an_empty_one(engine, monkeypatch):
    fake = _install(monkeypatch, _fake_universe())
    result = asyncio.run(pe_data.backfill_history(START, END))
    assert result.series_total == 5 and result.series_fetched == 4
    assert result.empty == [("industry", "Asset Management", "NYSE")] and result.failed == []
    assert not [r for r in _all(engine) if r.name == "Asset Management"]
    assert len(_all(engine)) == 8
    assert result.rows == {("sector", "NYSE"): 2, ("sector", "NASDAQ"): 2, ("industry", "NYSE"): 2, ("industry", "NASDAQ"): 2}
    hist = [c for c in fake.calls if c[0] == "hist"]
    assert all(c[4] == START.isoformat() and c[5] == END.isoformat() for c in hist)  # explicit from/to
    assert {c[2] for c in fake.calls if c[0] == "snap"} == {"NYSE", "NASDAQ", "AMEX"}  # discovery is per exchange


def test_backfill_is_idempotent_and_resumes_without_refetching_complete_series(engine, monkeypatch):
    _install(monkeypatch, _fake_universe())
    asyncio.run(pe_data.backfill_history(START, END))
    before = sorted((r.kind, r.name, r.exchange, r.date, r.pe) for r in _all(engine))

    fake2 = _install(monkeypatch, _fake_universe())
    again = asyncio.run(pe_data.backfill_history(START, END))
    assert sorted((r.kind, r.name, r.exchange, r.date, r.pe) for r in _all(engine)) == before  # no duplicates
    assert again.series_skipped == 4 and again.series_fetched == 0
    # only the empty series is asked again
    assert [c[2] for c in fake2.calls if c[0] == "hist"] == ["Asset Management"]

    fake3 = _install(monkeypatch, _fake_universe())
    forced = asyncio.run(pe_data.backfill_history(START, END, force=True))
    assert forced.series_fetched == 4 and len([c for c in fake3.calls if c[0] == "hist"]) == 5
    assert len(_all(engine)) == len(before)


def test_backfill_survives_one_failing_series_and_resumes_it(engine, monkeypatch):
    universe = _fake_universe()
    universe.fail = {("sector", "Energy", "NYSE")}
    _install(monkeypatch, universe)
    result = asyncio.run(pe_data.backfill_history(START, END))
    assert [f[:3] for f in result.failed] == [("sector", "Energy", "NYSE")]
    assert result.series_fetched == 3
    assert not [r for r in _all(engine) if (r.kind, r.name, r.exchange) == ("sector", "Energy", "NYSE")]

    _install(monkeypatch, _fake_universe())  # the next run completes only what is missing
    resumed = asyncio.run(pe_data.backfill_history(START, END))
    assert resumed.series_fetched == 1 and resumed.failed == []
    assert len(_all(engine)) == 8


def test_backfill_stops_when_the_group_goes_off_mid_run(engine, monkeypatch):
    from clients.fmp_client import FMPGroupDisabledError

    class Disabled(FakeFmp):
        async def _hist(self, *a, **k):
            raise FMPGroupDisabledError("off", group="sector_industry_pe")

    _install(monkeypatch, Disabled({"NYSE": ["Energy"]}, {}))
    with pytest.raises(FMPGroupDisabledError):
        asyncio.run(pe_data.backfill_history(START, END, exchanges=("NYSE",)))


def test_backfill_script_skips_while_the_group_is_off(monkeypatch, tmp_path):
    import pipeline.backfills.backfill_sector_industry_pe as script

    monkeypatch.setattr(script, "LOG_PATH", tmp_path / "x.log")
    monkeypatch.setattr(script, "init_db", lambda: None)
    called = []

    async def boom(**_k):
        called.append(1)

    monkeypatch.setattr(script, "backfill_history", boom)
    dg.set_group_enabled("sector_industry_pe", False)
    assert asyncio.run(script.main()) is None and not called


# --- nightly job -----------------------------------------------------------


def _snap_fake(fail=()):
    names = {e: ["Energy"] for e in pe_data.EXCHANGES}
    return FakeFmp(names, {e: ["Banks - Regional", "Software - Application"] for e in pe_data.EXCHANGES}, fail=fail)


def test_nightly_job_makes_six_calls_for_the_last_completed_trading_day_and_upserts(engine, monkeypatch):
    fake = _install(monkeypatch, _snap_fake())
    summary = asyncio.run(job.main())
    assert summary["attempted"] == 6 and summary["failed"] == 0 and summary["written"] == 9
    assert [c[3] for c in fake.calls] == [END.isoformat()] * 6
    assert {(c[1], c[2]) for c in fake.calls} == {(k, e) for k in ("sector", "industry") for e in pe_data.EXCHANGES}
    asyncio.run(job.main())  # a re-run (weekend, retry) is idempotent
    assert len(_all(engine)) == 9
    run = CronRunContext()
    job.record_outcome(summary, run)
    assert run.message and not run.skipped


def test_nightly_job_one_failed_call_is_isolated_but_all_failed_is_a_failure(engine, monkeypatch):
    _install(monkeypatch, _snap_fake(fail={("sector", "*", "AMEX")}))
    summary = asyncio.run(job.main())
    assert summary["failed"] == 1 and summary["written"] == 8  # 9 rows a night, minus the failed AMEX sector row
    job.record_outcome(summary, CronRunContext())  # one failure of six is a success with a message

    every = {(k, "*", e) for k in ("sector", "industry") for e in pe_data.EXCHANGES}
    _install(monkeypatch, _snap_fake(fail=every))
    dead = asyncio.run(job.main())
    with pytest.raises(RuntimeError):
        job.record_outcome(dead, CronRunContext())


def test_nightly_job_writing_no_rows_is_a_failure(engine, monkeypatch):
    _install(monkeypatch, FakeFmp({}, {}))
    summary = asyncio.run(job.main())
    assert summary["written"] == 0 and summary["no_data"] == 6
    with pytest.raises(RuntimeError):
        job.record_outcome(summary, CronRunContext())


def test_nightly_job_skips_without_a_call_while_the_group_or_master_is_off(engine, monkeypatch):
    fake = _install(monkeypatch, _snap_fake())
    dg.set_group_enabled("sector_industry_pe", False)
    summary = asyncio.run(job.main())
    assert summary["skipped"] and "sector_industry_pe" in summary["skip_reason"] and not fake.calls
    run = CronRunContext()
    job.record_outcome(summary, run)
    assert run.skipped

    dg.set_group_enabled("sector_industry_pe", True)
    dg.set_master(False)
    summary = asyncio.run(job.main())
    assert summary["skipped"] and "master switch" in summary["skip_reason"] and not fake.calls
    assert _all(engine) == []
