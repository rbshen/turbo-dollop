"""Regression guard: a cron job added to crontab.txt without also being
wired into core.cron_health.CRON_JOB_NAMES and its own script's entry
point would ship unmonitored -- exactly the class of blind spot this
system exists to close. This test fails loudly if that ever happens."""

import re
from pathlib import Path

from core.cron_health import CRON_JOB_NAMES

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
