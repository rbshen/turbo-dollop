"""One-off rebuild of stored Warren watch rows after the 2026-10-16 rule changes (a Gray Down at or below the entry price no longer
sets the stop; the seed replays 12 months instead of 3; docs/specs/warren-signals-page.md). Replays every non-removed row's candles
from REBUILD_START (the first seed's as_of minus SEED_MONTHS, a fixed date so a rerun is stable) through the row's own cursor with
the current rules, the cached 60m bars (a pure read: no FMP call) and today's LP settings, then compares every field with the
stored row.

Writes (only with --apply) the changed columns of a row that differs, and nothing else: `removed_at`, the cursor, `as_of` and
`last_updated_at` are never touched, a removed row is skipped (never resurrected) and a ticker with no row never gets one.

Mismatch guard. A row that already equals the new replay is identical (so a rerun after --apply reports every row identical). A row
that differs is only rebuilt if the same bars and LP settings, replayed under the OLD rules (the old 3-month window from SEED_START
and the old Gray Down stop rule, emulated here), reproduce the stored row exactly. If they do not, the difference is not explained
by the rule changes (the bars, the LP settings or the arrows moved), so the row is printed and skipped.

Run (writes nothing):
    uv run python -m pipeline.backfills.rebuild_warren_watch
Run for real:
    uv run python -m pipeline.backfills.rebuild_warren_watch --apply
"""

import argparse
import contextlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlmodel import Session, select

from analysis.warren_signal import watch as watch_rules
from analysis.warren_signal.watch import WatchState, advance
from clients.shared_bars_cache import INTRADAY_INTERVAL, _load_frames
from core.db import engine
from core.models import LiquidityZoneSettings, WarrenWatchCursor, WarrenWatchRow
from data.warren_signal_data import profile_for
from data.warren_watch_data import SEED_MONTHS, SecondSupportLookup, _row_values, _state_from_row, completed_candles, watch_replay
from helpers.liquidity_zone_config import to_engine_settings
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS

# The first seed's as_of (2026-10-15 15:30) minus SEED_MONTHS: the new replay start. SEED_START is the OLD 3-month start, kept only
# for the guard's old-rules replay.
FIRST_SEED_AS_OF = datetime(2026, 10, 15, 15, 30)
REBUILD_START = (pd.Timestamp(FIRST_SEED_AS_OF) - pd.DateOffset(months=SEED_MONTHS)).to_pydatetime()
SEED_START = datetime(2026, 7, 15, 15, 30)
# A 180-day engine warm-up before the replay start is the comfortable minimum for a clean left edge (warren-signal.md).
WARMUP_DAYS = 180

FIELDS = (
    "profile", "latest_arrow_kind", "latest_arrow_at", "instruction_type", "entry_kind", "entry_at", "entry_price", "stop_price",
    "stop_basis", "status", "breached_at", "last_signal_at",
)


def _old_apply_down(state: WatchState, kind: str, ts: datetime, pos: int, close: float, lp_second) -> WatchState:
    """The Gray Down rule before 2026-10-16: a yellow entry always set the stop to the entry price."""
    if kind == "gray_down" and state.status == watch_rules.STATUS_ACTIVE and state.entry_kind == watch_rules.ENTRY_YELLOW and state.entry_price is not None:
        moved = replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, instruction_type=watch_rules.GRAY_DOWN)
        return replace(moved, stop_price=state.entry_price, stop_basis=watch_rules.BASIS_ENTRY)
    return _new_apply_down(state, kind, ts, pos, close, lp_second)


_new_apply_down = watch_rules._apply_down


@contextlib.contextmanager
def old_gray_down_rule():
    watch_rules._apply_down = _old_apply_down
    try:
        yield
    finally:
        watch_rules._apply_down = _new_apply_down


def replay_state(ticker: str, bars: pd.DataFrame, settings, through: datetime, start: datetime = REBUILD_START) -> WatchState | None:
    """The row the CURRENT rules give for `ticker` from `start` through the candle `through`."""
    candles = completed_candles(bars, datetime.now(timezone.utc))
    candles = candles[candles.index <= pd.Timestamp(through)]
    if candles.empty:
        return None
    result = watch_replay(ticker, candles)
    return advance(None, candles, result.events, result.first_yellow_after_blue_at, profile_for(ticker).name, start, SecondSupportLookup(candles, settings))


def old_rules_state(ticker: str, bars: pd.DataFrame, settings, through: datetime) -> WatchState | None:
    """The row the rules in force when the table was seeded give: the 3-month window from SEED_START and the old Gray Down rule."""
    with old_gray_down_rule():
        return replay_state(ticker, bars, settings, through, SEED_START)


def diff(stored: WatchState, fresh: WatchState | None) -> dict[str, tuple]:
    if fresh is None:
        return {"<replay>": ("row", "no row")}
    return {f: (getattr(stored, f), getattr(fresh, f)) for f in FIELDS if getattr(stored, f) != getattr(fresh, f)}


def history_gap(bars: pd.DataFrame, through: datetime) -> str | None:
    """None when the cached bars start early enough (replay start minus the warm-up); else how much history there is."""
    candles = completed_candles(bars, datetime.now(timezone.utc))
    if candles.empty:
        return "no completed candles"
    first = candles.index[0].to_pydatetime()
    if first > REBUILD_START:
        return f"first candle {first:%Y-%m-%d}: less than 12 months before the first seed's as_of ({(FIRST_SEED_AS_OF - first).days} days)"
    if first > REBUILD_START - timedelta(days=WARMUP_DAYS):
        return f"first candle {first:%Y-%m-%d}: 12 months but under {WARMUP_DAYS} days of warm-up before the replay start"
    return None


def classify(old: dict) -> list[str]:
    """The kinds of change in a diff dict {field: (stored, new)}."""
    kinds = []
    if {"entry_kind", "entry_at", "entry_price"} & set(old):
        kinds.append("entry changed")
    if {"stop_price", "stop_basis"} & set(old):
        kinds.append("stop changed")
    if "status" in old:
        kinds.append(f"status {old['status'][0]} -> {old['status'][1]}")
    if {"instruction_type", "latest_arrow_kind", "latest_arrow_at"} & set(old):
        kinds.append("instruction/latest arrow changed")
    if {"last_signal_at", "breached_at", "profile"} & set(old) and not kinds:
        kinds.append("dates only")
    return kinds


def main(apply: bool, tickers: list[str] | None = None) -> dict:
    with Session(engine) as session:
        # Read the settings row directly, never get-or-create: this script writes nothing else.
        settings = to_engine_settings(session.get(LiquidityZoneSettings, "default"))
        stmt = select(WarrenWatchRow).where(WarrenWatchRow.removed_at.is_(None)).order_by(WarrenWatchRow.ticker)
        rows = [r for r in session.exec(stmt).all() if not tickers or r.ticker in tickers]
        cursors = {c.ticker: c.processed_through for c in session.exec(select(WarrenWatchCursor)).all()}
        bars = _load_frames(session, [r.ticker for r in rows], INTRADAY_INTERVAL, (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date())

        changing, same, skipped, gaps = [], 0, [], []
        for row in rows:
            frame, through = bars.get(row.ticker), cursors.get(row.ticker)
            if frame is None or frame.empty or through is None:
                skipped.append((row.ticker, "no cached bars or no cursor"))
                continue
            gap = history_gap(frame, through)
            if gap:
                gaps.append((row.ticker, gap))
            stored = _state_from_row(row)
            fresh = replay_state(row.ticker, frame, settings, through)
            if fresh is None:
                skipped.append((row.ticker, "12-month replay gives no row, left alone"))
                continue
            changes = diff(stored, fresh)
            if not changes:
                same += 1  # already on the current rules (a rerun after --apply)
                continue
            baseline = diff(stored, old_rules_state(row.ticker, frame, settings, through))
            if baseline:
                skipped.append((row.ticker, f"old rules do not reproduce the stored row, left alone: {baseline}"))
                continue
            changing.append((row.ticker, changes, stored, fresh))
            if apply:
                for field, value in _row_values(fresh).items():
                    setattr(row, field, value)
                session.add(row)
        if apply:
            session.commit()

    print(f"{'APPLIED' if apply else 'DRY RUN'}: {len(rows)} non-removed rows; {same} identical; {len(changing)} changing; {len(skipped)} skipped")
    kinds: dict[str, int] = {}
    for ticker, changes, stored, fresh in changing:
        ks = classify(changes)
        for k in ks:
            kinds[k] = kinds.get(k, 0) + 1
        print(f"  {ticker}: {', '.join(ks)}")
        for f, (a, b) in changes.items():
            print(f"      {f}: {a} -> {b}")
    print("by kind (a row can count in several):", dict(sorted(kinds.items())))
    for ticker, why in skipped:
        print(f"  SKIPPED {ticker}: {why}")
    for ticker, why in gaps:
        print(f"  HISTORY {ticker}: {why}")
    return {"changing": len(changing), "same": same, "skipped": len(skipped), "gaps": len(gaps), "kinds": kinds}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the changed rows (default: dry run)")
    main(parser.parse_args().apply)
