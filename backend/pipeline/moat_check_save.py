"""Validates the two blind passes of an independent Moat check, reconciles them and appends ONE MoatCheck row
(docs/specs/moat-check.md, "The command flow", step 4).

    cd backend && uv run python -m pipeline.moat_check_save <ticker> <pass1.json> <pass2.json> [<run_date YYYY-MM-DD>]

Not a cron job (no heartbeat, no CRON_JOB_NAMES entry). It writes through the app's engine, never calls `init_db` and never creates a
table: if `moatcheck` is missing it says so and stops. It touches nothing else: not TickerMoat, not a score, no recompute, no network.

Warnings (printed after the result line, never refusals): an empty prose field, and a pass whose checked_date differs from `run_date`.
Exit codes: 0 saved; 1 the table is missing; 2 invalid or unreadable input (every problem of BOTH passes printed, each line starting "pass 1:" or
"pass 2:" so the caller knows which pass to redo; nothing saved); 3 a known ETF or fund."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlmodel import Session

from core import db
from data.moat_check import MoatCheckValidationError, append_moat_check


def _read_pass(number: int, path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"pass {number}: {path}: {exc}") from exc


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save an independent Moat check (two blind passes) as one MoatCheck row.")
    parser.add_argument("ticker")
    parser.add_argument("pass1", type=Path)
    parser.add_argument("pass2", type=Path)
    parser.add_argument("run_date", nargs="?", help="YYYY-MM-DD; a pass with another checked_date gets a warning")
    args = parser.parse_args(argv)

    run_date = None
    if args.run_date is not None:
        try:
            run_date = date.fromisoformat(args.run_date)
        except ValueError:
            print(f"refused: run_date {args.run_date!r} is not a YYYY-MM-DD date", file=sys.stderr)
            return 2
    try:
        passes = [_read_pass(1, args.pass1), _read_pass(2, args.pass2)]
    except ValueError as exc:
        print(f"refused: cannot read a pass file: {exc}", file=sys.stderr)
        return 2

    engine = engine or db.engine
    if not inspect(engine).has_table("moatcheck"):
        print("moatcheck table is missing; start the app once so init_db creates it (this script never creates tables)", file=sys.stderr)
        return 1
    with Session(engine) as session:
        try:
            saved = append_moat_check(session, args.ticker, passes[0], passes[1], run_date=run_date)
        except MoatCheckValidationError as exc:
            print("refused: a pass record is invalid, nothing was saved:", file=sys.stderr)
            for problem in exc.problems:
                print(f"  {problem}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 3
        row = saved.row
        print(f"{row.ticker}: {row.rating or 'inconclusive'} ({row.status}), confidence {row.evidence_confidence}, proof {row.proof_basis}, row {row.id}")
        for warning in saved.warnings:
            print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
