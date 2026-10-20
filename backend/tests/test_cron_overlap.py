"""Cron overlap protection (crontab.txt, cleanup batch 2026-10-13): every active line runs under `flock -n -E 99` on its own lock file, a
second run of the same job while the first holds the lock is skipped with one log line, and different jobs never block each other.

The execution tests run the REAL line text (its flock wrapper, its skip echo) with only the backend directory pointed at a temp directory
and the job swapped for `sleep` / a marker command; cron's own `\\%` -> `%` unescaping is applied first."""

import re
import subprocess
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
LINES = [l for l in (BACKEND / "crontab.txt").read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
UV = "/home/shen/.local/bin/uv run python -m"


def _job(line: str) -> str:
    return re.search(r"-m ([\w.]+)", line).group(1).split(".")[-1]


def test_every_active_line_is_under_a_per_job_flock():
    assert LINES
    for line in LINES:
        job = _job(line)
        assert f"/usr/bin/flock -n -E 99 logs/locks/{job}.lock {UV} " in line, line
        assert "mkdir -p logs/locks &&" in line, line
        assert line.count("flock") == 1, f"double-locked: {line}"
        assert f"skipped {job}: the previous run is still going" in line, line


def test_lock_files_are_unique_per_job():
    # One lock per JOB, not per line: backup_db has a 3:30 daily and a Saturday 4:15 line that deliberately share backup_db.lock, so two
    # backups can never run at once.
    locks = {(_job(l), re.search(r"logs/locks/(\S+\.lock)", l).group(1)) for l in LINES}
    assert len({lock for _, lock in locks}) == len({job for job, _ in locks})


def test_schedule_and_command_are_otherwise_unchanged():
    for line in LINES:
        fields = line.split()[:5]
        assert len(fields) == 5
        assert re.fullmatch(r"cd /home/shen/fathom/backend && mkdir -p logs/locks && /usr/bin/flock -n -E 99 logs/locks/\w+\.lock "
                            r"/home/shen/\.local/bin/uv run python -m [\w.]+( --once)? >> \S+ 2>&1; "
                            r"\[ \$\? -ne 99 \] \|\| echo \"\$\(date -u \+\\%FT\\%TZ\) skipped \w+: the previous run is still going\" >> \S+",
                            line.split(None, 5)[5]), line
        log = re.search(r">> (\S+) 2>&1", line).group(1)
        assert line.endswith(f'>> {log}'), "the skip line goes to the same log as the job's output"


def test_no_script_locks_on_its_own_so_nothing_is_double_locked():
    # No script already locks (a double lock would make the cron lock fight an inner one).
    for path in list((BACKEND / "pipeline").glob("*.py")) + list((BACKEND / "scrapers").glob("*.py")):
        assert "flock" not in path.read_text(), path


def _runnable(line: str, tmp: Path, job_command: str) -> str:
    """The line's shell command with cron's unescaping applied, the backend dir swapped for `tmp` and the job swapped for `job_command`."""
    command = line.split(None, 5)[5].replace("\\%", "%")
    command = command.replace("/home/shen/fathom/backend", str(tmp))
    return command.replace(f"{UV} pipeline.{_job(line)}", job_command, 1) if f"{UV} pipeline.{_job(line)}" in command else command.replace(
        re.search(rf"{re.escape(UV)} [\w.]+(?: --once)?", command).group(0), job_command, 1
    )


@pytest.fixture
def box(tmp_path):
    (tmp_path / "logs").mkdir()
    return tmp_path


def _line(job: str) -> str:
    return next(l for l in LINES if _job(l) == job)


def test_an_overlapping_run_is_skipped_with_one_log_line(box):
    line = _line("nightly_fundamentals_fetch")
    log = box / "logs" / "nightly_fundamentals_fetch_cron.log"
    first = subprocess.Popen(["sh", "-c", _runnable(line, box, "sh -c 'echo first-started; sleep 2; echo first-done'")])
    deadline = time.monotonic() + 10
    while not (log.exists() and "first-started" in log.read_text()):
        assert time.monotonic() < deadline
        time.sleep(0.05)
    second = subprocess.run(["sh", "-c", _runnable(line, box, "sh -c 'echo second-RAN'")], timeout=10)
    assert second.returncode == 0  # the skip is not a failure of the cron line
    first.wait(timeout=10)
    text = log.read_text()
    assert "second-RAN" not in text
    assert text.count("skipped nightly_fundamentals_fetch: the previous run is still going") == 1
    assert re.search(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ skipped nightly_fundamentals_fetch", text, re.M)  # a real timestamp, % unescaped
    assert "first-done" in text


def test_after_the_first_run_ends_the_next_run_goes(box):
    line = _line("nightly_fundamentals_fetch")
    log = box / "logs" / "nightly_fundamentals_fetch_cron.log"
    subprocess.run(["sh", "-c", _runnable(line, box, "sh -c 'echo run-one'")], timeout=10)
    subprocess.run(["sh", "-c", _runnable(line, box, "sh -c 'echo run-two'")], timeout=10)
    assert log.read_text().split() == ["run-one", "run-two"] and "skipped" not in log.read_text()


def test_the_lock_is_released_when_the_job_fails(box):
    line = _line("nightly_fundamentals_fetch")
    log = box / "logs" / "nightly_fundamentals_fetch_cron.log"
    subprocess.run(["sh", "-c", _runnable(line, box, "sh -c 'echo crash; exit 3'")], timeout=10)
    subprocess.run(["sh", "-c", _runnable(line, box, "sh -c 'echo after-crash'")], timeout=10)
    text = log.read_text()
    assert "crash" in text and "after-crash" in text and "skipped" not in text  # exit 3 is the job's, not a lock conflict


def test_different_jobs_do_not_block_each_other(box):
    a, b = _line("nightly_fundamentals_fetch"), _line("nightly_sector_industry_pe")
    first = subprocess.Popen(["sh", "-c", _runnable(a, box, "sh -c 'sleep 1.5'")])
    time.sleep(0.4)
    subprocess.run(["sh", "-c", _runnable(b, box, "sh -c 'echo other-job-ran'")], timeout=10)
    first.wait(timeout=10)
    assert "other-job-ran" in (box / "logs" / "nightly_sector_industry_pe_cron.log").read_text()


def test_the_lock_directory_is_created_on_a_fresh_checkout(box):
    assert not (box / "logs" / "locks").exists()
    subprocess.run(["sh", "-c", _runnable(_line("backup_db"), box, "sh -c 'echo ok'")], timeout=10)
    assert (box / "logs" / "locks" / "backup_db.lock").exists()
