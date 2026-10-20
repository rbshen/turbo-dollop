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


def _crontab_entries() -> dict[str, list[tuple[str, str, str, str, str]]]:
    """module name -> the five raw cron time fields (minute, hour, dom, month, dow) of EVERY active line for it, in file order.
    pipeline.backup_db has two (the daily 3:30 and the Saturday 4:15, 2026-10-20)."""
    entries: dict[str, list[tuple[str, str, str, str, str]]] = {}
    for line in CRONTAB_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.search(r"-m ([\w.]+)", stripped)
        if match:
            entries.setdefault(match.group(1), []).append(tuple(stripped.split()[:5]))
    return entries


def _crontab_schedule() -> dict[str, tuple[str, str, str, str, str]]:
    """module name -> the five raw cron time fields of its FIRST active line (the primary schedule; for backup_db the daily 3:30 line, which
    is kept above the Saturday one in crontab.txt, and test_backup_db_runs_a_second_time_on_saturday_after_the_weekly_job pins both)."""
    return {module: lines[0] for module, lines in _crontab_entries().items()}


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
# since the 2026-10-02 reschedule: technical 1:00-1:40, ETFs screener 1:45 (2026-10-03), fundamentals 2:00, price-target
# sector/industry P/E 3:05, price-target 3:10, recompute 3:25, backup 3:30.
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
    "pipeline.nightly_etf_screener",
    "pipeline.nightly_fundamentals_fetch",
    "pipeline.nightly_sector_industry_pe",
    "pipeline.nightly_price_target_snapshot",
    "pipeline.nightly_score_recompute",
    "pipeline.backup_db",
]


def test_nightly_chain_runs_in_the_agreed_order():
    for earlier, later in zip(_NIGHTLY_CHAIN_ORDER, _NIGHTLY_CHAIN_ORDER[1:]):
        assert _daily_minute_of_day(earlier) < _daily_minute_of_day(later), (
            f"{earlier} must be scheduled before {later} (technical jobs first, fundamentals later)"
        )


def test_corporate_events_is_a_weekly_saturday_job_clear_of_every_other_fmp_job():
    """Weekly since 2026-10-14 (it feeds only the Chart E/D markers; disabled 2026-10-01 while it ran nightly at 406-527 calls/min). Saturday
    6:00 UTC. A run is ~582 tickers x 3 calls = ~1,750 calls paced at 150/min on Starter = ~12 min (about 20 at ~1,000 tickers); a catch-up run after
    downtime costs the same, because every call asks for the full history. So the slot must keep a 30-minute run window clear by >= 10 minutes on both
    sides of every other FMP-using job: the last nightly FMP job is price-target (3:10, ends ~3:20), the Saturday 4:00 opportunity job uses no FMP,
    and the next FMP-using job is the Sunday 12:30 AM stale-data check."""
    name = "pipeline.nightly_corporate_events"
    assert name in CRON_JOB_NAMES and name not in DISABLED_CRON_JOBS
    minute, hour, dom, month, dow = _crontab_schedule()[name]
    assert (dom, month, dow) == ("*", "*", "6"), f"{name} is a Saturday job, got {(minute, hour, dom, month, dow)}"
    start = int(hour) * 60 + int(minute)
    window = 30  # covers the ~12 min normal run and the ~20 min run at ~1,000 tickers
    assert start == JOB_METADATA[name].sort_minutes == 6 * 60
    # Every nightly (daily) FMP job has long finished on the Saturday morning: the latest daily start is 3:45 (no FMP), price-target 3:10.
    last_daily_fmp = _daily_minute_of_day("pipeline.nightly_price_target_snapshot")
    assert start >= last_daily_fmp + 10 + 10, "must start after the price-target job (worst seen ~10 min) with >= 10 min margin"
    assert start >= _daily_minute_of_day("pipeline.backup_db") + 10
    minute, hour, *_ = _crontab_schedule()["pipeline.weekly_opportunity_snapshot"]
    assert start >= int(hour) * 60 + int(minute) + 10  # the Saturday 4:00 job (stored data only) is long done
    # The next day's first FMP job is the Sunday block (00:00 onward, i.e. 24:00 on the Saturday clock) and the 1:00 daily chain.
    assert start + window + 10 <= 24 * 60
    # Saturday's own nightly chain starts at 1:00, 5 hours before.
    assert start > _daily_minute_of_day("pipeline.nightly_score_recompute")


def test_corporate_events_is_a_weekly_job_with_a_weekly_cadence_not_a_disabled_one():
    from core.cron_health import _EXPECTED_CADENCE_HOURS, _WEEKLY_HOURS

    name = "pipeline.nightly_corporate_events"
    assert name not in DISABLED_CRON_JOBS, "re-enabled weekly 2026-10-14: it must not be listed as disabled again without a decision"
    assert _EXPECTED_CADENCE_HOURS[name] == _WEEKLY_HOURS == 24 * 8, "weekly cadence: overdue only after 8 days, never on a non-run day"
    metadata = JOB_METADATA[name]
    assert metadata.cadence_group == "weekly" and metadata.time_label == "Sat 6:00 AM"


def test_no_two_daily_jobs_share_a_minute():
    # Same-minute starts risk SQLite writer-lock contention (2026-09-11 cron audit).
    seen: dict[tuple[str, str], str] = {}
    for module, (minute, hour, dom, month, dow) in _crontab_schedule().items():
        if (dom, month, dow) != ("*", "*", "*"):
            continue
        key = (hour, minute)
        assert key not in seen, f"{module} and {seen[key]} both start at {hour}:{minute}"
        seen[key] = module


_SATURDAY_JOBS = {"pipeline.weekly_opportunity_snapshot", "pipeline.nightly_corporate_events"}


def _weekly_minutes() -> dict[str, int]:
    """module -> minute-of-day, for every job in the Sunday block. The weekly jobs NOT in it are the Saturday 4:00 AM opportunity
    snapshot and the Saturday 6:00 AM corporate-events refresh (`_SATURDAY_JOBS`), which run after the whole nightly chain and the
    backup; any other weekday is a mistake."""
    out = {}
    for module, (minute, hour, dom, month, dow) in _crontab_schedule().items():
        if module in _SATURDAY_JOBS:
            assert (dom, month, dow) == ("*", "*", "6"), f"{module}: expected Saturday (dow 6), got {dow!r}"
            continue
        if dow != "*":
            assert (dom, month, dow) == ("*", "*", "0"), f"{module}: weekly jobs are expected on Sunday (dow 0), got {dow!r}"
            out[module] = int(hour) * 60 + int(minute)
    return out


def test_sunday_block_finishes_before_the_daily_chain_starts():
    """The index-list refreshes and the weekly maintenance jobs (Sundays 12:00-12:40 AM, the
    slowest, stale_data_health_check, ~2.6 min) run BEFORE the 1:00 AM daily chain, so a
    constituent change is picked up the same night and nothing overlaps the first job.
    Needs at least 15 minutes between the last weekly start and the first daily job."""
    weekly = _weekly_minutes()
    assert len(weekly) == 9, f"expected the 9 weekly jobs, got {sorted(weekly)}"  # 9th: prune_audit_log, 12:40 (2026-10-13)
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


def test_etf_screener_runs_after_its_inputs_with_room_on_both_sides():
    """The ETF job reads the bars the trend job fills and the signal rows LP, BB+RSI and Warren write (Warren's
    worst seen run is ~5.4 min, its window 10), so it needs >= 10 min after the latest of them starts + its window;
    and it must end (steady state 1-3 min) before fundamentals, the planned corporate-events slot when enabled,
    the recompute and the backup."""
    etf = _daily_minute_of_day("pipeline.nightly_etf_screener")
    assert etf >= _daily_minute_of_day("pipeline.nightly_warren_signal_calculation") + 15
    for upstream in (
        "pipeline.nightly_trend_calculation",
        "pipeline.nightly_liquidity_zone_calculation",
        "pipeline.nightly_entry_signal_calculation",
        "pipeline.nightly_warren_signal_calculation",
    ):
        assert etf > _daily_minute_of_day(upstream)
    assert etf + 10 <= _daily_minute_of_day("pipeline.nightly_fundamentals_fetch")
    assert etf + 10 <= _daily_minute_of_day("pipeline.nightly_score_recompute")
    assert etf + 10 <= _daily_minute_of_day("pipeline.backup_db")


def test_sector_industry_pe_runs_after_fundamentals_and_before_the_jobs_that_follow():
    """6 calls, ~5 s. It follows the fundamentals fetch's worst-seen run (64.5 min -> ends 3:04:30), so it never competes
    with it for FMP or the SQLite writer, and it ends before price-target (3:10) and the recompute (3:25)."""
    pe = _daily_minute_of_day("pipeline.nightly_sector_industry_pe")
    assert pe >= _daily_minute_of_day("pipeline.nightly_fundamentals_fetch") + 65
    assert pe + 5 <= _daily_minute_of_day("pipeline.nightly_price_target_snapshot")
    assert pe + 10 <= _daily_minute_of_day("pipeline.nightly_score_recompute")


def test_the_outcome_updater_runs_after_the_backup_and_well_before_the_saturday_weekly_job():
    """The updater (3:40) starts after the last job of the nightly chain, the backup, with room: the backup took 3:30-3:35 at worst over the
    10 nights to 2026-10-12. It is a few seconds of work, and the Saturday weekly opportunity job (4:00) starts 20 minutes later."""
    updater = _daily_minute_of_day("pipeline.opportunity_outcome_update")
    assert updater >= _daily_minute_of_day("pipeline.backup_db") + 8
    schedule = _crontab_schedule()
    minute, hour, *_ = schedule["pipeline.weekly_opportunity_snapshot"]
    assert int(hour) * 60 + int(minute) - updater >= 15


def test_the_outcome_updater_is_a_daily_job_with_a_daily_cadence():
    from core.cron_health import _DAILY_HOURS, _EXPECTED_CADENCE_HOURS

    name = "pipeline.opportunity_outcome_update"
    assert name in CRON_JOB_NAMES and name not in DISABLED_CRON_JOBS
    assert _EXPECTED_CADENCE_HOURS[name] == _DAILY_HOURS == 36
    assert _crontab_schedule()[name][2:] == ("*", "*", "*")



def test_the_daily_flag_job_runs_between_the_outcome_updater_and_the_saturday_job():
    """Phase 2b v1, scheduled 2026-10-12 at 3:45 UTC: after the 03:40 outcome updater (which prices its flags the NEXT night) and at least
    15 minutes before the Saturday 4:00 weekly job, after the whole nightly chain (the backup), daily on a 36 h cadence."""
    from core.cron_health import _DAILY_HOURS, _EXPECTED_CADENCE_HOURS

    name = "pipeline.opportunity_daily_flags"
    assert name in CRON_JOB_NAMES and name in JOB_METADATA and name not in DISABLED_CRON_JOBS
    assert _EXPECTED_CADENCE_HOURS[name] == _DAILY_HOURS == 36
    assert _crontab_schedule()[name][2:] == ("*", "*", "*")
    scheduled = _daily_minute_of_day(name)
    assert scheduled == JOB_METADATA[name].sort_minutes == 3 * 60 + 45
    assert scheduled >= _daily_minute_of_day("pipeline.opportunity_outcome_update") + 5
    assert scheduled >= _daily_minute_of_day("pipeline.backup_db") + 8
    minute, hour, *_ = _crontab_schedule()["pipeline.weekly_opportunity_snapshot"]
    assert int(hour) * 60 + int(minute) - scheduled >= 15


def test_backup_db_has_exactly_the_daily_line_first_and_one_saturday_line():
    lines = _crontab_entries()["pipeline.backup_db"]
    assert lines == [("30", "3", "*", "*", "*"), ("15", "4", "*", "*", "6")], lines
    assert JOB_METADATA["pipeline.backup_db"].sort_minutes == 3 * 60 + 30  # the display row is the daily line


def test_the_saturday_backup_runs_after_the_weekly_job_and_before_the_next_scheduled_job():
    """Saturday 4:15: the weekly opportunity job starts 4:00 and took 12 s (04:00:03-04:00:15 on 2026-10-17), so 15 minutes after its start leaves
    >= 14 min of margin; the 3:30 backup took 113-307 s over 69 successful runs, so it is long finished; and the Saturday 4:15 backup (same
    ~5 min worst) ends > 90 min before the next scheduled job of that morning, the 6:00 corporate-events refresh."""
    saturday = [f for f in _crontab_entries()["pipeline.backup_db"] if f[4] == "6"]
    assert len(saturday) == 1
    minute, hour, dom, month, dow = saturday[0]
    assert (dom, month) == ("*", "*")
    start = int(hour) * 60 + int(minute)
    weekly_minute, weekly_hour, *_ = _crontab_schedule()["pipeline.weekly_opportunity_snapshot"]
    weekly = int(weekly_hour) * 60 + int(weekly_minute)
    assert start >= weekly + 10, "the weekly job (~15 s) must be finished with a wide margin"
    assert start >= _daily_minute_of_day("pipeline.backup_db") + 30, "the Saturday 3:30 backup (<= ~5 min) must be long finished"
    assert start >= _daily_minute_of_day("pipeline.opportunity_daily_flags") + 20  # nor overlap the 3:30-3:45 chain
    # Every other job that runs on a Saturday (daily lines included): none inside [start - 10, start + 30] (a backup takes up to ~5 min).
    for module, lines in _crontab_entries().items():
        for m, h, d, mo, w in lines:
            if (module, (m, h, d, mo, w)) == ("pipeline.backup_db", saturday[0]):
                continue
            if w in ("*", "6"):
                other = int(h) * 60 + int(m)
                assert not (start - 10 <= other <= start + 30), f"{module} at {h}:{m} is too close to the Saturday 4:15 backup"
    later = [int(h) * 60 + int(m) for module, lines in _crontab_entries().items() for m, h, d, mo, w in lines if w in ("*", "6") and int(h) * 60 + int(m) > start]
    assert min(later) - start >= 90, "the next scheduled job after the Saturday backup (corporate events 6:00) must leave >= 90 minutes"
