"""Prepares one independent Moat check run (docs/specs/moat-check.md, "The command flow", step 1-2 and "Enforcement").

    cd backend && uv run python -m pipeline.moat_check_prepare <ticker>

What it does, in order:
  1. validates the ticker and removes run folders under /tmp/moat-check/ that are over a day old (failed runs are kept for that long);
  2. builds the blind data block (pipeline/moat_check_block.py, database opened `mode=ro`); a refusal (ETF, no cached data) stops here, before
     anything is created;
  3. creates /tmp/moat-check/<TICKER>-<timestamp>/pass1/ and pass2/, each holding a byte-identical copy of docs/specs/moat-criteria.md
     (criteria.md) and the block (block.json): the only files a pass can read, enforced by .claude/hooks/moat-pass-guard.py;
  4. probes the guard hook command of both agent files as the shell would run it (a denied path must exit 2, an allowed one 0), so a broken
     or missing hook command (Claude Code treats any exit other than 2 as non-blocking) is caught here, not discovered mid-run. The probe
     proves the command works; that Claude Code calls it is what the phase 6 trial checks;
  5. prints key=value lines (run_dir, pass1_dir, pass2_dir, run_date, stale_cutoff) and the screen-only cache dates.

RUN_DATE is today's system date; the 18-month stale cutoff is computed here (month arithmetic, day clamped) and passed to the passes
explicitly. Nothing here reads TickerMoat, TickerScore or MoatCheck.

Exit codes: 0 ready; 2 refused (bad ticker, or the block cannot be built); 3 the guard probe failed (run folder removed)."""

import calendar
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from core.tickers import normalize_ticker
from pipeline.moat_check_block import BlockRefused, load_block

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = Path("/tmp/moat-check")
CRITERIA_SOURCE = REPO_ROOT / "docs" / "specs" / "moat-criteria.md"
AGENT_FILES = (REPO_ROOT / ".claude" / "agents" / "moat-pass-1.md", REPO_ROOT / ".claude" / "agents" / "moat-pass-2.md")
STALE_MONTHS = 18
RUN_MAX_AGE = timedelta(days=1)
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.-][A-Z0-9]{1,3})?$")


class PrepareRefused(Exception):
    """The run cannot be prepared; the message says why."""


def valid_ticker(raw: str) -> str:
    """The normalised ticker, or PrepareRefused for anything that is not a single ticker symbol."""
    ticker = normalize_ticker(raw or "")
    if not TICKER_PATTERN.fullmatch(ticker):
        raise PrepareRefused(f"{raw!r} is not a single ticker symbol (letters and digits, optional '.' or '-' suffix)")
    return ticker


def stale_cutoff(run_date: date, months: int = STALE_MONTHS) -> date:
    """`months` calendar months before `run_date`, the day clamped to the target month's length (31 Aug - 6 months = 28/29 Feb)."""
    index = run_date.year * 12 + (run_date.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(run_date.day, calendar.monthrange(year, month)[1]))


def sweep(base: Path, now: datetime | None = None, max_age: timedelta = RUN_MAX_AGE) -> list[Path]:
    """Removes run folders directly under `base` whose last change is older than `max_age` (a symlink or a plain file, such as guard.log,
    is never touched). Returns what it removed."""
    now = now or datetime.now()
    removed: list[Path] = []
    if not base.is_dir():
        return removed
    for child in sorted(base.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        if now - datetime.fromtimestamp(child.stat().st_mtime) > max_age:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child)
    return removed


def guard_commands(agent_files=AGENT_FILES) -> list[tuple[int, str]]:
    """(pass number, hook command) read from each agent file's frontmatter."""
    found = []
    for number, path in enumerate(agent_files, start=1):
        text = path.read_text()
        match = re.search(r'^\s*command:\s*"((?:[^"\\]|\\.)*)"\s*$', text, re.MULTILINE)
        if not match:
            raise PrepareRefused(f"{path.name} has no hook command")
        found.append((number, match.group(1).replace('\\"', '"').replace("\\\\", "\\")))
    return found


def probe_guard(run_dir: Path, commands: list[tuple[int, str]] | None = None) -> None:
    """Runs each pass's hook command as the shell would, with a denied and an allowed payload; raises PrepareRefused if the exit codes are
    not 2 and 0."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)}
    for number, command in commands if commands is not None else guard_commands():
        probes = (
            ({"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}, 2),
            ({"tool_name": "Read", "tool_input": {"file_path": str(run_dir / f"pass{number}" / "criteria.md")}}, 0),
            ({"tool_name": "Read", "tool_input": {"file_path": str(run_dir / f"pass{3 - number}" / "criteria.md")}}, 2),
        )
        for payload, expected in probes:
            result = subprocess.run(["sh", "-c", command], input=json.dumps(payload), text=True, capture_output=True, env=env, timeout=30)
            if result.returncode != expected:
                raise PrepareRefused(
                    f"the guard hook of pass {number} answered exit {result.returncode} (expected {expected}) for "
                    f"{payload['tool_input']['file_path']}: {(result.stderr or result.stdout).strip()[:200]}"
                )


def prepare(
    raw_ticker: str,
    *,
    base: Path = BASE_DIR,
    today: date | None = None,
    now: datetime | None = None,
    db_path: Path | None = None,
    criteria: Path = CRITERIA_SOURCE,
    probe: bool = True,
    commands: list[tuple[int, str]] | None = None,
) -> dict:
    """Does steps 1 to 4 above and returns the values to print. Raises PrepareRefused (bad ticker, block refused, probe failed)."""
    ticker = valid_ticker(raw_ticker)
    now = now or datetime.now()
    today = today or now.date()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    sweep(base, now)
    try:
        block, info = load_block(ticker, db_path)
    except BlockRefused as exc:
        raise PrepareRefused(str(exc)) from exc

    stamp = now.strftime("%Y%m%d-%H%M%S")
    run_dir = base / f"{ticker}-{stamp}"
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = base / f"{ticker}-{stamp}-{suffix}"
    block_text = json.dumps(block, indent=1)
    for number in (1, 2):
        folder = run_dir / f"pass{number}"
        folder.mkdir(parents=True, mode=0o700)
        shutil.copyfile(criteria, folder / "criteria.md")
        (folder / "block.json").write_text(block_text)
    if probe:
        try:
            probe_guard(run_dir, commands)
        except PrepareRefused:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
    return {
        "ticker": ticker,
        "run_dir": run_dir,
        "run_date": today,
        "stale_cutoff": stale_cutoff(today),
        "info": info,
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m pipeline.moat_check_prepare <ticker>", file=sys.stderr)
        return 2
    try:
        result = prepare(argv[0])
    except PrepareRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3 if "guard hook" in str(exc) else 2
    run_dir, info = result["run_dir"], result["info"]
    print(f"run_dir={run_dir}")
    print(f"pass1_dir={run_dir / 'pass1'}")
    print(f"pass2_dir={run_dir / 'pass2'}")
    print(f"run_date={result['run_date'].isoformat()}")
    print(f"stale_cutoff={result['stale_cutoff'].isoformat()}")
    fiscal = info["fiscal_dates"]
    print(f"ticker={result['ticker']}")
    print(f"margins: {info['margin_rule']}")
    print(f"statement fiscal dates read: {fiscal[0]} to {fiscal[-1]} ({len(fiscal)} years)")
    print(f"last bar date: {info['last_bar_date']} ({info['bar_source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
