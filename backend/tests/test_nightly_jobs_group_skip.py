"""Phase 6b decision 2: with no fallback provider, a nightly bar job whose data group is off reports
a real `skipped` cron status instead of computing on stale cached bars and reading as "success"."""

import asyncio
import importlib

import pytest

import core.data_groups as dg
from core.cron_health import CronRunContext

DAILY_JOBS = [
    "pipeline.nightly_trend_calculation",
    "pipeline.nightly_liquidity_zone_calculation",
    "pipeline.nightly_sector_heatmap",
    "pipeline.nightly_market_breadth",
]
INTRADAY_JOBS = ["pipeline.nightly_warren_signal_calculation", "pipeline.nightly_entry_signal_calculation"]


def _load(monkeypatch, tmp_path, name):
    job = importlib.import_module(name)
    monkeypatch.setattr(job, "init_db", lambda: None)
    if hasattr(job, "LOG_PATH"):
        monkeypatch.setattr(job, "LOG_PATH", tmp_path / "x.log")
    return job


def _forbid_any_bar_fetch(monkeypatch):
    import clients.shared_bars_cache as cache

    async def boom(*_a, **_k):
        raise AssertionError("a skipped job must not fetch bars")

    monkeypatch.setattr(cache, "get_or_fetch_bars_batch", boom)
    for module in ("data.market_breadth_data", "data.sector_heatmap_data", "data.momentum_data", "pipeline.nightly_trend_calculation",
                   "pipeline.nightly_liquidity_zone_calculation", "pipeline.nightly_warren_signal_calculation"):
        mod = importlib.import_module(module)
        if hasattr(mod, "get_or_fetch_bars_batch"):
            monkeypatch.setattr(mod, "get_or_fetch_bars_batch", boom)


@pytest.mark.parametrize("name", DAILY_JOBS)
def test_daily_bar_jobs_skip_while_daily_prices_is_off(monkeypatch, tmp_path, name):
    job = _load(monkeypatch, tmp_path, name)
    _forbid_any_bar_fetch(monkeypatch)
    dg.set_group_enabled("daily_prices", False)

    summary = asyncio.run(job.main())

    assert summary["skipped"] is True and "daily_prices" in summary["skip_reason"]


@pytest.mark.parametrize("name", INTRADAY_JOBS)
def test_intraday_bar_jobs_skip_while_intraday_bars_is_off(monkeypatch, tmp_path, name):
    job = _load(monkeypatch, tmp_path, name)
    _forbid_any_bar_fetch(monkeypatch)
    dg.set_group_enabled("intraday_bars", False)

    summary = asyncio.run(job.main())

    assert summary["skipped"] is True and "intraday_bars" in summary["skip_reason"]


def test_the_master_switch_skips_every_bar_job(monkeypatch, tmp_path):
    _forbid_any_bar_fetch(monkeypatch)
    dg.set_master(False)
    for name in DAILY_JOBS + INTRADAY_JOBS:
        job = _load(monkeypatch, tmp_path, name)
        summary = asyncio.run(job.main())
        assert summary["skipped"] is True and "master switch" in summary["skip_reason"]


def test_the_momentum_job_skips_its_group_off_run_but_not_a_non_anchor_day(monkeypatch, tmp_path):
    from datetime import date

    job = _load(monkeypatch, tmp_path, "pipeline.monthly_momentum_snapshot")
    _forbid_any_bar_fetch(monkeypatch)
    dg.set_group_enabled("daily_prices", False)

    summary = asyncio.run(job.main(force_anchor=date(2026, 9, 1)))
    assert summary["group_skipped"] is True and "daily_prices" in summary["reason"]

    monkeypatch.setattr(job, "resolve_month_end_anchor", lambda today: None)
    other = asyncio.run(job.main())
    assert other["skipped"] is True and "group_skipped" not in other  # the ordinary "not the first trading day" no-op


def test_a_skipped_summary_is_recorded_as_a_skipped_heartbeat():
    run = CronRunContext()
    run.skip("skipped (group daily_prices off)")
    assert run.skipped is True and run.message == "skipped (group daily_prices off)"
