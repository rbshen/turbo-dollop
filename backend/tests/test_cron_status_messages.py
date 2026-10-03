"""Status messages and the shared failure threshold for the nightly jobs that report
attempted/failed counts (core.cron_health.check_failure_threshold + each job's record_outcome)."""

import pytest

import pipeline.backup_db as backup_db
import pipeline.nightly_entry_signal_calculation as entry_signal
import pipeline.nightly_fundamentals_fetch as fundamentals
import pipeline.nightly_score_recompute as score_recompute
import pipeline.nightly_warren_signal_calculation as warren
from core.cron_health import (
    FAILURE_RATE_MIN_ATTEMPTED,
    FAILURE_RATE_THRESHOLD,
    CronRunContext,
    check_failure_threshold,
)


def test_threshold_constants_are_the_documented_values():
    assert FAILURE_RATE_THRESHOLD == 0.05
    assert FAILURE_RATE_MIN_ATTEMPTED == 25


@pytest.mark.parametrize(
    "attempted, failed",
    [
        (100, 0),  # nothing failed
        (100, 4),  # below 5%
        (60, 2),  # 3.3%
        (0, 0),  # nothing attempted
        (24, 2),  # tiny run (under the minimum): 8% but the rate rule is off
        (10, 1),  # tiny run, one error
        (3, 2),  # tiny run, not everything failed
    ],
)
def test_threshold_passes(attempted, failed):
    check_failure_threshold(attempted, failed, "summary")


@pytest.mark.parametrize(
    "attempted, failed",
    [
        (100, 5),  # exactly 5%
        (100, 6),  # above
        (600, 30),  # exactly 5% at production scale
        (25, 2),  # smallest run where the rate rule applies, 8%
        (590, 590),  # everything failed
        (3, 3),  # everything failed, tiny run
        (1, 1),
    ],
)
def test_threshold_fails(attempted, failed):
    with pytest.raises(RuntimeError, match="summary"):
        check_failure_threshold(attempted, failed, "summary")


def test_one_error_never_trips_a_run_big_enough_for_the_rate_rule():
    for attempted in range(FAILURE_RATE_MIN_ATTEMPTED, 400):
        check_failure_threshold(attempted, 1, "summary")


def test_failure_text_carries_the_summary_and_the_reason():
    with pytest.raises(RuntimeError) as exc:
        check_failure_threshold(200, 20, "180 ok, 20 failed")
    assert "180 ok, 20 failed" in str(exc.value) and "10.0%" in str(exc.value)
    with pytest.raises(RuntimeError) as exc:
        check_failure_threshold(4, 4, "0 ok, 4 failed")
    assert "all 4 attempted failed" in str(exc.value)


# --- per-job messages -------------------------------------------------------


def test_fundamentals_message_and_threshold():
    run = CronRunContext()
    fundamentals.record_outcome({"processed": 587, "failed": 2, "calls_made": 2626, "duration_seconds": 2670.0}, run)
    assert run.message == "585 refreshed, 2 failed, 2,626 FMP calls, 44.5 min"
    assert run.skipped is False

    with pytest.raises(RuntimeError, match="refreshed"):
        fundamentals.record_outcome({"processed": 100, "failed": 5, "calls_made": 10, "duration_seconds": 60.0}, CronRunContext())


def test_fundamentals_gated_run_is_skipped():
    run = CronRunContext()
    fundamentals.record_outcome({"skipped": True, "skip_reason": "skipped (group fundamentals disabled)"}, run)
    assert run.skipped and run.message == "skipped (group fundamentals disabled)"


@pytest.mark.parametrize(
    "module, stale_part",
    [(entry_signal, ", 2 still stale after fetch"), (warren, "")],
)
def test_signal_jobs_message_threshold_and_skip(module, stale_part):
    run = CronRunContext()
    module.record_outcome({"processed": 105, "failed": 1, "swept": 3, "pruned": 12, "stale_count": 2}, run)
    assert run.message == "104 computed, 1 failed, 3 swept, 12 pruned" + stale_part

    with pytest.raises(RuntimeError, match="computed"):
        module.record_outcome({"processed": 105, "failed": 6, "swept": 0, "pruned": 0, "stale_count": 0}, CronRunContext())

    empty = CronRunContext()  # no monitored tickers: processed 0 is a success, not a failure
    module.record_outcome({"processed": 0, "failed": 0, "swept": 0, "pruned": 0, "stale_count": 0}, empty)
    assert empty.message == "0 computed, 0 failed, 0 swept, 0 pruned" + (", 0 still stale after fetch" if stale_part else "")

    # A large stale count alone never fails the run (informational, like the daily-bar jobs).
    all_stale = CronRunContext()
    module.record_outcome({"processed": 105, "failed": 0, "swept": 0, "pruned": 0, "stale_count": 105}, all_stale)
    assert not all_stale.skipped and all_stale.message

    gated = CronRunContext()
    module.record_outcome({"skipped": True, "skip_reason": "skipped (group intraday_bars disabled)"}, gated)
    assert gated.skipped


def test_score_recompute_message_counts_skips_and_excludes_them_from_the_threshold():
    run = CronRunContext()
    score_recompute.record_outcome({"processed": 587, "skipped": 4, "failed": 1}, run)
    assert run.message == "582 scored, 4 skipped (no cached profile), 1 failed"

    # 300 skipped of 330 would be a bad denominator for 5 failures if skips counted as attempts...
    # here 30 attempted, 5 failed = 16.7% -> failure.
    with pytest.raises(RuntimeError, match="scored"):
        score_recompute.record_outcome({"processed": 330, "skipped": 300, "failed": 5}, CronRunContext())

    # ...and a large skip count alone never fails the run.
    quiet = CronRunContext()
    score_recompute.record_outcome({"processed": 100, "skipped": 100, "failed": 0}, quiet)
    assert quiet.message == "0 scored, 100 skipped (no cached profile), 0 failed"


def test_recompute_all_reports_skipped(monkeypatch):
    import asyncio

    import pipeline.recompute_ticker_scores as recompute
    from core.models import TickerScore
    from datetime import datetime

    async def fake_compute(ticker, cache_only=False):
        return None if ticker == "NOPROFILE" else TickerScore(ticker=ticker, overall_score=1, overall_verdict="Fail", computed_at=datetime.now())

    monkeypatch.setattr(recompute, "compute_ticker_score", fake_compute)
    result = asyncio.run(recompute.recompute_all(["AAPL", "NOPROFILE"]))
    assert (result["processed"], result["skipped"], result["failed"]) == (2, 1, 0)


def test_backup_message_has_size_and_rotation_count():
    run = CronRunContext()
    backup_db.record_outcome(145.93, 2, run)
    assert run.message == "145.9 MB, 2 old backup(s) pruned"


def test_backup_main_reports_size_and_pruned_count(monkeypatch, tmp_path):
    backup = tmp_path / "fathom_20261002_033000.db.gz"
    backup.write_bytes(b"x" * (3 * 1024 * 1024))
    monkeypatch.setattr(backup_db, "LOG_PATH", tmp_path / "backup_db_test.log")
    monkeypatch.setattr(backup_db, "_create_backup", lambda: (backup, [tmp_path / "old1", tmp_path / "old2"]))
    path, size_mb, pruned = backup_db.main()
    assert (path, size_mb, pruned) == (backup, 3.0, 2)
