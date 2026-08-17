import asyncio

from sqlmodel import SQLModel, create_engine

import pipeline.monthly_price_target_snapshot as monthly


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(monthly, "engine", engine)
    # main() calls configure_logging(LOG_PATH) with force=True, which
    # reconfigures the ROOT logger for the rest of this pytest process --
    # pointing it at a tmp_path file instead of the real production log
    # keeps test runs from polluting backend/logs/monthly_price_target_snapshot.log.
    monkeypatch.setattr(monthly, "LOG_PATH", tmp_path / "test_monthly_price_target_snapshot.log")
    return engine


def test_fmp_disabled_skips_the_run_before_any_fetch_or_universe_lookup(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(monthly.settings, "fmp_enabled", False)

    def fail_if_queried(*args, **kwargs):
        raise AssertionError("must not resolve the ticker universe while FMP is paused")

    monkeypatch.setattr(monthly, "load_universe_tickers", fail_if_queried)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("must not fetch price targets while FMP is paused")

    monkeypatch.setattr(monthly.fmp_client, "get_price_target_consensus", fail_if_called)

    summary = asyncio.run(monthly.main())  # tickers=None -- would normally resolve the full universe

    assert summary == {"processed": 0, "failed": 0, "calls_made": 0, "duration_seconds": 0.0, "failures": [], "skipped": True}


def test_fmp_disabled_skips_even_with_an_explicit_ticker_list(monkeypatch, tmp_path):
    # The guard is unconditional, same as nightly_fundamentals_fetch.py's
    # equivalent -- an explicit ticker list (e.g. from --tickers/--limit)
    # doesn't bypass it.
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(monthly.settings, "fmp_enabled", False)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("must not fetch price targets while FMP is paused")

    monkeypatch.setattr(monthly.fmp_client, "get_price_target_consensus", fail_if_called)

    summary = asyncio.run(monthly.main(tickers=["AAPL", "MSFT"]))

    assert summary["skipped"] is True
    assert summary["processed"] == 0
