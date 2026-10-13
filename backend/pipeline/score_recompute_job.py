"""The worker behind the background score recompute (data/score_recompute.py): re-scores every tracked ticker through the full
`compute_ticker_score` path, cache only (zero FMP calls), at the saved weights, reporting progress on its ScoreRecomputeRun row.

Not a cron job (no CronRunLog row): the API starts it as a subprocess and the run row is its status.

    uv run python -m pipeline.score_recompute_job <run_id> [--tickers AAPL,MSFT]

Per-ticker failures are collected (a bad ticker never stops the run). The run ends `done`, or `failed` when the job itself crashed
or every ticker failed. Each score row is one atomic upsert, so no row is ever half written whatever happens.

Lifecycle (2026-10-13): the heartbeat is written every PROGRESS_EVERY tickers or every HEARTBEAT_EVERY_SECONDS, whichever comes first (a
slow ticker or a lock wait cannot outrun the 120 s stale window); the worker stops itself with a failed run at
`SCORE_RECOMPUTE_TIMEOUT_SECONDS`; and it stops at once when its run row is no longer `running` (the API reaped it), instead of writing
`done` over a `failed` row.
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from sqlmodel import Session

from core.db import engine
from core.logging_config import configure_logging
from core.models import ScoreRecomputeRun
from core.tickers import normalize_ticker
from data.score_recompute import timeout_seconds
from data.score_weights import load_score_weights
from data.ticker_score import compute_ticker_score
from data.tracked_universe import load_tracked_universe

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "score_recompute_job.log"
PROGRESS_EVERY = 10  # tickers between status writes (each is also the heartbeat)
HEARTBEAT_EVERY_SECONDS = 10.0  # ... or this long, whichever comes first
MAX_FAILURES_KEPT = 50

logger = logging.getLogger(__name__)


class RunSuperseded(Exception):
    """The run row is no longer `running` (the API reaped it as stale or timed out): this worker must stop and write nothing more."""


def _update(run_id: int, **fields) -> None:
    with Session(engine) as session:
        run = session.get(ScoreRecomputeRun, run_id)
        if run.state != "running":
            raise RunSuperseded(f"run {run_id} is {run.state}")
        for key, value in fields.items():
            setattr(run, key, value)
        run.heartbeat_at = datetime.now()
        session.add(run)
        session.commit()


async def run_job(
    run_id: int,
    tickers: list[str] | None = None,
    compute: Callable[..., Awaitable] = compute_ticker_score,
) -> dict:
    """Runs the recompute for an already claimed run and records how it ended. `compute` is injectable for tests."""
    started = time.monotonic()
    limit = timeout_seconds()
    try:
        if tickers is None:
            with Session(engine) as session:
                tickers = load_tracked_universe(session)
        _update(run_id, total=len(tickers), weights_version=load_score_weights(engine).version)

        processed = skipped = failed = 0
        failures: list[list[str]] = []
        last_beat = time.monotonic()
        for ticker in tickers:
            if limit > 0 and time.monotonic() - started > limit:
                raise TimeoutError(f"it ran past its {limit:.0f} s time limit after {processed} of {len(tickers)} tickers")
            try:
                result = await compute(ticker, cache_only=True)
                if result is None:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001 -- a single bad ticker must never abort the whole run
                failed += 1
                if len(failures) < MAX_FAILURES_KEPT:
                    failures.append([ticker, str(exc)])
                logger.error("%s: FAILED - %s", ticker, exc)
            processed += 1
            if processed % PROGRESS_EVERY == 0 or time.monotonic() - last_beat >= HEARTBEAT_EVERY_SECONDS:
                _update(run_id, processed=processed, skipped=skipped, failed=failed)
                last_beat = time.monotonic()

        everything_failed = processed > 0 and failed == processed
        _update(
            run_id,
            processed=processed,
            skipped=skipped,
            failed=failed,
            failures_json=json.dumps(failures),
            state="failed" if everything_failed else "done",
            error="Every ticker failed to score." if everything_failed else None,
            finished_at=datetime.now(),
        )
        logger.info("Recompute run %s finished: %d processed, %d skipped, %d failed in %.1fs", run_id, processed, skipped, failed, time.monotonic() - started)
        return {"processed": processed, "skipped": skipped, "failed": failed}
    except RunSuperseded as exc:
        logger.warning("Recompute run %s stopped: %s", run_id, exc)
        return {"processed": 0, "skipped": 0, "failed": 0, "superseded": True}
    except Exception as exc:  # noqa: BLE001 -- the job itself broke: say so on the run row, then re-raise for the log
        logger.exception("Recompute run %s crashed", run_id)
        try:
            _update(run_id, state="failed", error=f"The recompute stopped: {exc}", finished_at=datetime.now())
        except RunSuperseded:
            pass  # the API already marked it failed
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Background full score recompute (started by the API).")
    parser.add_argument("run_id", type=int)
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated explicit list (tests and proofs only).")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    configure_logging(LOG_PATH)
    tickers = [normalize_ticker(t) for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    asyncio.run(run_job(args.run_id, tickers))


if __name__ == "__main__":
    main()
