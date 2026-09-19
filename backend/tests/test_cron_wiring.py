"""Regression guard: a cron job added to crontab.txt without also being
wired into core.cron_health.CRON_JOB_NAMES and its own script's entry
point would ship unmonitored -- exactly the class of blind spot this
system exists to close. This test fails loudly if that ever happens."""

import re
from pathlib import Path

from core.cron_health import CRON_JOB_NAMES, JOB_METADATA

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
    crontab_modules = _crontab_module_names()
    assert crontab_modules == set(CRON_JOB_NAMES), (
        f"crontab.txt and CRON_JOB_NAMES have drifted apart. "
        f"In crontab.txt but not CRON_JOB_NAMES: {crontab_modules - set(CRON_JOB_NAMES)}. "
        f"In CRON_JOB_NAMES but not crontab.txt: {set(CRON_JOB_NAMES) - crontab_modules}."
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
