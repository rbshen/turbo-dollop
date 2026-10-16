"""One-time correction of stored Warren watch rows after the 2026-10-16 rule change (a Gray Up on a BREACHED row no longer
advances `last_signal_at`; docs/specs/warren-signals-page.md). Replays every non-removed row's candles from the ORIGINAL seed
start (SEED_START, not a slid 3-month window, so entries and no-entry rows stay as seeded) through the row's own cursor with the
current rules and the cached 60m bars (a pure read: no FMP call), then compares the result with the stored row.

Only a row whose single difference is `last_signal_at` is corrected, and only that column is written: `removed_at`, the cursor,
`last_updated_at` and `as_of` are never touched, a removed row is skipped (never resurrected), and any row that differs in any
other field is printed and left alone for review (for example a ticker seeded later than SEED_START, or an LP setting that changed).

Run (writes nothing):
    uv run python -m pipeline.backfills.rebuild_warren_watch
Run for real:
    uv run python -m pipeline.backfills.rebuild_warren_watch --apply
"""

import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlmodel import Session, select

from analysis.warren_signal.watch import WatchState, advance
from clients.shared_bars_cache import INTRADAY_INTERVAL, _load_frames
from core.db import engine
from core.models import WarrenWatchCursor, WarrenWatchRow
from data.warren_signal_data import profile_for
from data.warren_watch_data import SecondSupportLookup, _state_from_row, completed_candles, watch_replay
from helpers.liquidity_zone_config import get_liquidity_zone_settings, to_engine_settings
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS

# The first seed's window start: as_of 2026-10-15 15:30 minus SEED_MONTHS (3).
SEED_START = datetime(2026, 7, 15, 15, 30)

FIELDS = (
    "profile", "latest_arrow_kind", "latest_arrow_at", "instruction_type", "entry_kind", "entry_at", "entry_price", "stop_price",
    "stop_basis", "status", "breached_at", "last_signal_at",
)


def replay_state(ticker: str, bars: pd.DataFrame, settings, through: datetime) -> WatchState | None:
    """The row the current rules give for `ticker` from SEED_START through the candle `through`."""
    candles = completed_candles(bars, datetime.now(timezone.utc))
    candles = candles[candles.index <= pd.Timestamp(through)]
    if candles.empty:
        return None
    result = watch_replay(ticker, candles)
    return advance(None, candles, result.events, result.first_yellow_after_blue_at, profile_for(ticker).name, SEED_START, SecondSupportLookup(candles, settings))


def diff(stored: WatchState, fresh: WatchState | None) -> dict[str, tuple]:
    if fresh is None:
        return {"<replay>": ("row", "no row")}
    return {f: (getattr(stored, f), getattr(fresh, f)) for f in FIELDS if getattr(stored, f) != getattr(fresh, f)}


def main(apply: bool) -> dict:
    with Session(engine) as session:
        settings = to_engine_settings(get_liquidity_zone_settings(session))
        rows = list(session.exec(select(WarrenWatchRow).where(WarrenWatchRow.removed_at.is_(None)).order_by(WarrenWatchRow.ticker)).all())
        cursors = {c.ticker: c.processed_through for c in session.exec(select(WarrenWatchCursor)).all()}
        bars = _load_frames(session, [r.ticker for r in rows], INTRADAY_INTERVAL, (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date())

        corrected, same, skipped = [], 0, []
        for row in rows:
            frame, through = bars.get(row.ticker), cursors.get(row.ticker)
            if frame is None or frame.empty or through is None:
                skipped.append((row.ticker, "no cached bars or no cursor"))
                continue
            changes = diff(_state_from_row(row), replay_state(row.ticker, frame, settings, through))
            if not changes:
                same += 1
            elif set(changes) == {"last_signal_at"}:
                corrected.append((row.ticker, *changes["last_signal_at"]))
                if apply:
                    row.last_signal_at = changes["last_signal_at"][1]
                    session.add(row)
            else:
                skipped.append((row.ticker, f"other differences, left alone: {changes}"))
        if apply:
            session.commit()

    print(f"{'APPLIED' if apply else 'DRY RUN'}: {len(rows)} non-removed rows; {same} identical; {len(corrected)} last_signal_at corrections; {len(skipped)} skipped")
    for ticker, old, new in corrected:
        print(f"  {ticker}: last_signal_at {old} -> {new}")
    for ticker, why in skipped:
        print(f"  SKIPPED {ticker}: {why}")
    return {"corrected": len(corrected), "same": same, "skipped": len(skipped)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the corrections (default: dry run)")
    main(parser.parse_args().apply)
