"""Regression guard: a cron job added to crontab.txt without also being
wired into core.cron_health.CRON_JOB_NAMES and its own script's entry
point would ship unmonitored -- exactly the class of blind spot this
system exists to close. This test fails loudly if that ever happens."""

import re
from pathlib import Path

from core.cron_health import CRON_JOB_NAMES, DISABLED_CRON_JOBS, JOB_METADATA

BACKEND_DIR = Path(__file__).resolve().parent.parent
CRONTAB_PATH = BACKEND_DIR / "crontab.txt"

# job_name -> the script file that owns it (dotted module path -> file path).
_JOB_NAME_TO_FILE = {job_name: BACKEND_DIR / (job_name.replace(".", "/") + ".py") for job_name in CRON_JOB_NAMES}


def _crontab_module_names() -> set[str]:
    modules = set()
    for line in CRONTAB_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.search(r"-m ([\w.]+)", stripped)
        if match:
            modules.add(match.group(1))
    return modules


def test_crontab_and_cron_job_names_agree():
    # A job in DISABLED_CRON_JOBS is deliberately commented out of crontab.txt but still
    # listed in CRON_JOB_NAMES/JOB_METADATA; every other job must be scheduled.
    assert set(DISABLED_CRON_JOBS) <= set(CRON_JOB_NAMES), (
        f"DISABLED_CRON_JOBS names a job that is not in CRON_JOB_NAMES: {set(DISABLED_CRON_JOBS) - set(CRON_JOB_NAMES)}"
    )
    crontab_modules = _crontab_module_names()
    expected = set(CRON_JOB_NAMES) - set(DISABLED_CRON_JOBS)
    assert crontab_modules == expected, (
        f"crontab.txt and CRON_JOB_NAMES have drifted apart. "
        f"In crontab.txt but not CRON_JOB_NAMES (or listed in DISABLED_CRON_JOBS): {crontab_modules - expected}. "
        f"In CRON_JOB_NAMES but not crontab.txt (and not in DISABLED_CRON_JOBS): {expected - crontab_modules}."
    )


def test_every_cron_job_file_exists():
    for job_name, path in _JOB_NAME_TO_FILE.items():
        assert path.is_file(), f"{job_name} -> {path} does not exist"


def test_every_cron_job_script_calls_cron_heartbeat():
    for job_name, path in _JOB_NAME_TO_FILE.items():
        source = path.read_text()
        assert "cron_heartbeat(" in source, f"{path} does not call cron_heartbeat(...) -- unmonitored cron job"
        assert f'cron_heartbeat("{job_name}")' in source, (
            f"{path} calls cron_heartbeat(...) with a job_name that doesn't match "
            f"its own CRON_JOB_NAMES entry ({job_name!r})"
        )


def test_job_metadata_matches_cron_job_names():
    # A job could otherwise ship with live health tracking but no display
    # metadata for the Settings "Status" section's Scheduled Jobs table
    # (or vice versa, a stale entry left behind after a job is removed).
    assert set(JOB_METADATA.keys()) == set(CRON_JOB_NAMES), (
        f"JOB_METADATA and CRON_JOB_NAMES have drifted apart. "
        f"In JOB_METADATA but not CRON_JOB_NAMES: {set(JOB_METADATA) - set(CRON_JOB_NAMES)}. "
        f"In CRON_JOB_NAMES but not JOB_METADATA: {set(CRON_JOB_NAMES) - set(JOB_METADATA)}."
    )


def _crontab_schedule() -> dict[str, tuple[str, str, str, str, str]]:
    """module name -> the five raw cron time fields (minute, hour, dom, month, dow)."""
    schedule = {}
    for line in CRONTAB_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.search(r"-m ([\w.]+)", stripped)
        if match:
            schedule[match.group(1)] = tuple(stripped.split()[:5])
    return schedule


def _daily_minute_of_day(module: str) -> int:
    minute, hour, dom, month, dow = _crontab_schedule()[module]
    assert (dom, month, dow) == ("*", "*", "*"), f"{module} is expected to be a plain daily job, got {(minute, hour, dom, month, dow)}"
    return int(hour) * 60 + int(minute)


def test_score_recompute_runs_after_every_job_it_copies_from():
    """compute_ticker_score copies Trend/Weinstein, BB+RSI and Warren output
    onto TickerScore, so the full-universe recompute has to run after all of
    them -- at 2:50 (before all three) the Screener read a night-old copy
    (36 tickers' Weinstein stage disagreed with their own TrendAnalysis row).
    Also has to finish before the nightly backup so the backup holds it."""
    recompute = _daily_minute_of_day("pipeline.nightly_score_recompute")
    for upstream in (
        "pipeline.nightly_trend_calculation",
        "pipeline.nightly_entry_signal_calculation",
        "pipeline.nightly_warren_signal_calculation",
    ):
        assert recompute > _daily_minute_of_day(upstream), (
            f"nightly_score_recompute must be scheduled after {upstream}, or TickerScore's copy of its output is a night behind"
        )
    assert recompute < _daily_minute_of_day("pipeline.backup_db")


def test_job_metadata_sort_minutes_match_crontab():
    for module, (minute, hour, *_rest) in _crontab_schedule().items():
        assert JOB_METADATA[module].sort_minutes == int(hour) * 60 + int(minute), (
            f"{module}: JOB_METADATA says minute-of-day {JOB_METADATA[module].sort_minutes} "
            f"but crontab.txt schedules it at {hour}:{minute}"
        )


# The nightly chain order (2026-09-30): technical first, fundamentals later. Times
# since the 2026-10-02 reschedule: technical 1:00-1:40, fundamentals 2:00, price-target
# 3:10, recompute 3:25, backup 3:30.
# Each consecutive pair must be scheduled strictly later than the one before,
# so a schedule edit can't silently regress the agreed order. Hard constraints
# (trend fills the bar cache before LP/Sector/Breadth; BB+RSI before Warren;
# recompute after the technical jobs and before the backup) are a subset.
_NIGHTLY_CHAIN_ORDER = [
    "pipeline.nightly_last_close_snapshot",
    "pipeline.nightly_trend_calculation",
    "pipeline.nightly_liquidity_zone_calculation",
    "pipeline.nightly_entry_signal_calculation",
    "pipeline.nightly_warren_signal_calculation",
    "pipeline.nightly_sector_heatmap",
    "pipeline.nightly_market_breadth",
    "pipeline.nightly_fundamentals_fetch",
    "pipeline.nightly_price_target_snapshot",
    "pipeline.nightly_score_recompute",
    "pipeline.backup_db",
]


def test_nightly_chain_runs_in_the_agreed_order():
    for earlier, later in zip(_NIGHTLY_CHAIN_ORDER, _NIGHTLY_CHAIN_ORDER[1:]):
        assert _daily_minute_of_day(earlier) < _daily_minute_of_day(later), (
            f"{earlier} must be scheduled before {later} (technical jobs first, fundamentals later)"
        )


def test_corporate_events_runs_after_technical_jobs_and_before_fundamentals():
    if "pipeline.nightly_corporate_events" in DISABLED_CRON_JOBS:
        # Disabled 2026-10-01 (see DISABLED_CRON_JOBS): no schedule to check. Re-enabling
        # it makes this assertion live again.
        return
    events = _daily_minute_of_day("pipeline.nightly_corporate_events")
    assert _daily_minute_of_day("pipeline.nightly_market_breadth") < events
    assert events < _daily_minute_of_day("pipeline.nightly_fundamentals_fetch")


def test_no_two_daily_jobs_share_a_minute():
    # Same-minute starts risk SQLite writer-lock contention (2026-09-11 cron audit).
    seen: dict[tuple[str, str], str] = {}
    for module, (minute, hour, dom, month, dow) in _crontab_schedule().items():
        if (dom, month, dow) != ("*", "*", "*"):
            continue
        key = (hour, minute)
        assert key not in seen, f"{module} and {seen[key]} both start at {hour}:{minute}"
        seen[key] = module


def _weekly_minutes() -> dict[str, int]:
    """module -> minute-of-day, for every job scheduled on a single weekday (the weekly block)."""
    out = {}
    for module, (minute, hour, dom, month, dow) in _crontab_schedule().items():
        if dow != "*":
            assert (dom, month, dow) == ("*", "*", "0"), f"{module}: weekly jobs are expected on Sunday (dow 0), got {dow!r}"
            out[module] = int(hour) * 60 + int(minute)
    return out


def test_sunday_block_finishes_before_the_daily_chain_starts():
    """The index-list refreshes and the weekly maintenance jobs (Sundays 12:00-12:35 AM, the
    slowest, stale_data_health_check, ~2.6 min) run BEFORE the 1:00 AM daily chain, so a
    constituent change is picked up the same night and nothing overlaps the first job.
    Needs at least 15 minutes between the last weekly start and the first daily job."""
    weekly = _weekly_minutes()
    assert len(weekly) == 8, f"expected the 8 weekly jobs, got {sorted(weekly)}"
    first_daily = _daily_minute_of_day("pipeline.nightly_last_close_snapshot")
    assert max(weekly.values()) + 15 <= first_daily, (
        f"the last weekly job starts at minute {max(weekly.values())} but the daily chain starts at {first_daily}: "
        f"keep >= 15 min so the slowest weekly job finishes first"
    )


def test_fundamentals_starts_after_the_technical_chain_with_room_for_a_long_run():
    """Fundamentals (typically 1-5 min, 44.6 on the 2026-10-01 cache-expiry wave, 64.5 worst seen)
    must end before price-target (3:10): 64.5 min after its start leaves >= 5 minutes."""
    fundamentals = _daily_minute_of_day("pipeline.nightly_fundamentals_fetch")
    assert _daily_minute_of_day("pipeline.nightly_market_breadth") + 15 <= fundamentals
    assert fundamentals + 65 <= _daily_minute_of_day("pipeline.nightly_price_target_snapshot")
