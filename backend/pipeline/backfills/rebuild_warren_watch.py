"""One-off rebuild of stored Warren watch rows after a rule change (docs/specs/warren-signals-page.md); the current one is the
2026-10-17 gray-entry / breached-row rules. Replays every non-removed row's candles from REBUILD_START (the first seed's as_of
minus SEED_MONTHS, a fixed date so a rerun is stable) through the row's own cursor with the CURRENT rules (arrow rules plus the
trailing stop), the cached 60m bars (a pure read: no FMP call) and today's LP settings, and compares every field with the stored row.

Writes (only with --apply) the changed columns of a row that differs, and nothing else: `removed_at`, the cursor, `as_of` and
`last_updated_at` are never touched, a removed row is skipped (never resurrected) and a ticker with no row never gets one.

Mismatch guard. A row that already equals the new replay is identical (so a rerun after --apply reports every row identical). A row
that differs is only rebuilt if the same bars and LP settings replayed under the PREVIOUS arrow rules (`GUARD_RULES` = `PREVIOUS_RULES`: the rules before the 2026-10-17 Gray Down raise-only change, i.e. a
Gray Down set the stop to the entry price even when that lowered it; trailing on) reproduce the stored row exactly on
all fourteen fields. If they do not, the difference is not explained by the rule change (the bars, the LP settings or the arrows
moved), so the row is printed and skipped.

A dry run reads even when the database has not yet been migrated to the stop-age columns (it selects only the columns that exist);
--apply refuses until they exist (start the app or run a job once: init_db adds them).

Run (writes nothing):
    uv run python -m pipeline.backfills.rebuild_warren_watch [--show MRNA,QCOM]
Run for real:
    uv run python -m pipeline.backfills.rebuild_warren_watch --apply
"""

import argparse
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import pandas as pd
from sqlalchemy import inspect
from sqlmodel import Session, select

from analysis.warren_signal.watch import CURRENT_RULES, PREVIOUS_RULES, STATUS_ACTIVE, STATUS_BREACHED, WatchRules, WatchState, advance
from clients.shared_bars_cache import INTRADAY_INTERVAL, _load_frames
from core.db import engine
from core.models import LiquidityZoneSettings, WarrenWatchCursor, WarrenWatchRow
from data.warren_signal_data import profile_for
from data.warren_watch_data import SEED_MONTHS, SecondSupportLookup, _row_values, _state_from_row, completed_candles, watch_replay
from helpers.liquidity_zone_config import to_engine_settings
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS

# The first seed's as_of (2026-10-15 15:30) minus SEED_MONTHS: the replay start.
FIRST_SEED_AS_OF = datetime(2026, 10, 15, 15, 30)
REBUILD_START = (pd.Timestamp(FIRST_SEED_AS_OF) - pd.DateOffset(months=SEED_MONTHS)).to_pydatetime()
# A 180-day engine warm-up before the replay start is the comfortable minimum for a clean left edge (warren-signal.md).
WARMUP_DAYS = 180

# The rules the stored rows were built under: the guard replays these (PREVIOUS_RULES = before the Gray Down raise-only change).
GUARD_RULES = PREVIOUS_RULES

# The fields the arrow rules and the guard cover. The stop-age fields are filled on every row since the 2026-10-16 rebuild, so the guard compares all fourteen.
GUARD_FIELDS = (
    "profile", "latest_arrow_kind", "latest_arrow_at", "instruction_type", "entry_kind", "entry_at", "entry_price", "stop_price",
    "stop_basis", "status", "breached_at", "last_signal_at",
)
AGE_FIELDS = ("stop_moved_at", "stop_moved_by")
FIELDS = GUARD_FIELDS + AGE_FIELDS
ARROW_FIELDS = ("latest_arrow_kind", "latest_arrow_at", "instruction_type")


class Replay(NamedTuple):
    state: WatchState | None
    lp_calls: int
    trail_log: list  # (candle, old stop, new stop) per trail move


def replay_state(
    ticker: str, bars: pd.DataFrame, settings, through: datetime, start: datetime = REBUILD_START, trail: bool = True,
    rules: WatchRules = CURRENT_RULES,
) -> Replay:
    """The row the rules give for `ticker` from `start` through the candle `through` (`trail=False`: without the trailing stop;
    `rules`: the arrow rules, CURRENT_RULES or PREVIOUS_RULES)."""
    candles = completed_candles(bars, datetime.now(timezone.utc))
    candles = candles[candles.index <= pd.Timestamp(through)]
    if candles.empty:
        return Replay(None, 0, [])
    result = watch_replay(ticker, candles)
    lookup, log = SecondSupportLookup(candles, settings), []
    state = advance(None, candles, result.events, result.first_yellow_after_blue_at, profile_for(ticker).name, start, lookup, trail, log, rules)
    return Replay(state, lookup.calls, log)


def diff(stored: WatchState, fresh: WatchState | None, fields: tuple[str, ...] = FIELDS) -> dict[str, tuple]:
    if fresh is None:
        return {"<replay>": ("row", "no row")}
    return {f: (getattr(stored, f), getattr(fresh, f)) for f in fields if getattr(stored, f) != getattr(fresh, f)}


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


def classify(changes: dict) -> list[str]:
    """The kinds of change in a diff dict {field: (stored, new)}."""
    kinds = []
    if "entry_kind" in changes and changes["entry_kind"][1] == "gray":
        kinds.append("restarted as gray entry")
    if {"entry_kind", "entry_at", "entry_price"} & set(changes):
        kinds.append("entry changed")
    if "stop_price" in changes:
        kinds.append("stop changed")
    if "stop_basis" in changes:
        kinds.append("basis changed")
    if "status" in changes:
        kinds.append(f"status {changes['status'][0]} -> {changes['status'][1]}")
    if {"instruction_type", "latest_arrow_kind", "latest_arrow_at"} & set(changes):
        kinds.append("instruction/latest arrow changed")
    if {"last_signal_at", "breached_at", "profile"} & set(changes) and not kinds:
        kinds.append("dates only")
    if not kinds and set(changes) <= set(AGE_FIELDS):
        kinds.append("stop age fill only")
    return kinds


def _read_rows(session: Session, tickers: list[str] | None) -> tuple[list[WarrenWatchRow], bool]:
    """Every non-removed row, and whether the table already has the stop-age columns. Without them (a database not yet migrated)
    only the existing columns are selected, so a dry run needs no schema change."""
    present = {c["name"] for c in inspect(session.get_bind()).get_columns(WarrenWatchRow.__tablename__)}
    migrated = set(AGE_FIELDS) <= present
    if migrated:
        stmt = select(WarrenWatchRow).where(WarrenWatchRow.removed_at.is_(None)).order_by(WarrenWatchRow.ticker)
        rows = list(session.exec(stmt).all())
    else:
        cols = [c for c in WarrenWatchRow.__table__.c if c.name in present]
        stmt = select(*cols).where(WarrenWatchRow.removed_at.is_(None)).order_by(WarrenWatchRow.ticker)
        rows = [WarrenWatchRow.model_construct(**dict(zip([c.name for c in cols], r))) for r in session.exec(stmt).all()]
    return [r for r in rows if not tickers or r.ticker in tickers], migrated


def _brief(state: WatchState) -> str:
    stop = "no stop" if state.stop_price is None else f"stop {state.stop_price:.2f} {state.stop_basis}"
    entry = "no entry" if state.entry_price is None else f"entry {state.entry_price:.2f} {state.entry_kind} {state.entry_at:%Y-%m-%d %H:%M}"
    moved = f"moved {state.stop_moved_at:%Y-%m-%d %H:%M} by {state.stop_moved_by}" if state.stop_moved_at else "stop age null"
    return f"{entry}; {stop}; {state.status}{f' {state.breached_at:%Y-%m-%d %H:%M}' if state.breached_at else ''}; {moved}"


def main(apply: bool, tickers: list[str] | None = None, show: tuple[str, ...] = ()) -> dict:
    started = time.monotonic()
    with Session(engine) as session:
        # Read the settings row directly, never get-or-create: this script writes nothing else.
        settings = to_engine_settings(session.get(LiquidityZoneSettings, "default"))
        rows, migrated = _read_rows(session, tickers)
        if apply and not migrated:
            raise SystemExit("WarrenWatchRow has no stop_moved_at/stop_moved_by columns yet: start the app (or run a job) once so init_db adds them.")
        cursors = {c.ticker: c.processed_through for c in session.exec(select(WarrenWatchCursor)).all()}
        bars = _load_frames(session, [r.ticker for r in rows], INTRADAY_INTERVAL, (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date())

        changing, same, skipped, gaps, spotlight, finals, downs_ignored = [], 0, [], [], {}, {}, []
        lp_calls, trail_moves = 0, 0
        for row in rows:
            frame, through = bars.get(row.ticker), cursors.get(row.ticker)
            if frame is None or frame.empty or through is None:
                skipped.append((row.ticker, "no cached bars or no cursor"))
                continue
            gap = history_gap(frame, through)
            if gap:
                gaps.append((row.ticker, gap))
            stored = _state_from_row(row)
            new = replay_state(row.ticker, frame, settings, through)
            lp_calls += new.lp_calls
            trail_moves += len(new.trail_log)
            fresh = new.state
            if fresh is None:
                skipped.append((row.ticker, "12-month replay gives no row, left alone"))
                continue
            if row.ticker in show:
                spotlight[row.ticker] = (stored, fresh, new.trail_log)
            changes = diff(stored, fresh)
            if not changes:
                same += 1  # already on the current rules (a rerun after --apply)
                finals[row.ticker] = fresh
                continue
            old = replay_state(row.ticker, frame, settings, through, rules=GUARD_RULES)
            lp_calls += old.lp_calls
            baseline = diff(stored, old.state)
            if baseline:
                effect = diff(old.state, fresh)  # what the rule change alone would do to this row, on today's bars (the drift aside)
                skipped.append((
                    row.ticker,
                    f"the previous rules do not reproduce the stored row, left alone: {baseline}; "
                    f"the rule change alone would {'change ' + ', '.join(effect) if effect else 'change nothing'}",
                ))
                continue
            # What ignoring down arrows on a breached row does to this row on its own: the current rules with those arrows applied.
            applied = replay_state(row.ticker, frame, settings, through, rules=replace(CURRENT_RULES, ignore_breached_downs=False))
            lp_calls += applied.lp_calls
            if applied.state is not None and any(getattr(applied.state, f) != getattr(fresh, f) for f in ARROW_FIELDS):
                downs_ignored.append(row.ticker)
            changing.append((row.ticker, changes, stored, fresh))
            finals[row.ticker] = fresh
            if apply:
                for field, value in _row_values(fresh).items():
                    setattr(row, field, value)
                session.add(row)
        if apply:
            session.commit()

    print(f"{'APPLIED' if apply else 'DRY RUN'}: {len(rows)} non-removed rows; {same} identical; {len(changing)} changing; {len(skipped)} skipped")
    kinds: dict[str, int] = {}
    flips = []
    for ticker, changes, stored, fresh in changing:
        ks = classify(changes)
        for k in ks:
            kinds[k] = kinds.get(k, 0) + 1
        if set(changes) - set(AGE_FIELDS) and set(changes) <= {"stop_price", "stop_basis", *AGE_FIELDS}:
            kinds["stop only"] = kinds.get("stop only", 0) + 1
        if stored.status == STATUS_ACTIVE and fresh.status == STATUS_BREACHED:
            flips.append((ticker, fresh.breached_at))
        print(f"  {ticker}: {', '.join(ks)}")
        for f, (a, b) in changes.items():
            print(f"      {f}: {a} -> {b}")
    print("by kind (a row can count in several):", dict(sorted(kinds.items())))
    print(f"active -> breached ({len(flips)}):", ", ".join(f"{t} {d:%Y-%m-%d %H:%M}" for t, d in flips))
    to_active = [t for t, _, stored, fresh in changing if stored.status == STATUS_BREACHED and fresh.status == STATUS_ACTIVE]
    got_entry = [t for t, _, stored, fresh in changing if stored.entry_kind is None and fresh.entry_kind is not None]
    gray_restarts = [t for t, _, stored, fresh in changing if fresh.entry_kind == "gray" and stored.entry_kind != "gray"]
    arrow_changed = [t for t, ch, _, _ in changing if set(ch) & set(ARROW_FIELDS)]
    print(f"breached -> active ({len(to_active)}):", ", ".join(to_active))
    print(f"no entry -> entry ({len(got_entry)}):", ", ".join(got_entry))
    print(f"rows now on a gray entry that were not ({len(gray_restarts)}):", ", ".join(gray_restarts))
    print(f"rows whose arrow/instruction fields change from stored ({len(arrow_changed)}), of which because down arrows on a breached row are now ignored ({len([t for t in downs_ignored if t in arrow_changed])}):", ", ".join(t for t in downs_ignored if t in arrow_changed))
    print(f"rows where ignoring down arrows changes the final arrow fields at all ({len(downs_ignored)}):", ", ".join(downs_ignored))
    no_entry_left = sorted(t for t, f in finals.items() if f.entry_kind is None)
    print(f"rows with no entry after the rebuild ({len(no_entry_left)}):", ", ".join(no_entry_left))
    for ticker, (stored, fresh, log) in spotlight.items():
        print(f"  SHOW {ticker}\n      before: {_brief(stored)}\n      after:  {_brief(fresh)}\n      trail moves: {len(log)}")
    for ticker, why in skipped:
        print(f"  SKIPPED {ticker}: {why}")
    for ticker, why in gaps:
        print(f"  HISTORY {ticker}: {why}")
    filled = sum(1 for f in finals.values() if f.stop_moved_at is not None)
    no_stop = sum(1 for f in finals.values() if f.stop_price is None)
    no_age_with_stop = sum(1 for f in finals.values() if f.stop_price is not None and f.stop_moved_at is None)
    print(f"stop_moved_at after the rebuild ({len(finals)} rows with a verdict): {filled} filled; {len(finals) - filled} null ({no_stop} with no stop, {no_age_with_stop} with a stop)")
    print(f"{lp_calls} LP calls (trailing replays and guard replays); {trail_moves} trail moves; {time.monotonic() - started:.1f}s")
    return {
        "to_active": to_active, "got_entry": got_entry, "gray_restarts": gray_restarts, "arrow_changed": arrow_changed,
        "downs_ignored": downs_ignored, "no_entry_left": no_entry_left,
        "changing": len(changing), "same": same, "skipped": len(skipped), "gaps": len(gaps), "kinds": kinds, "flips": flips,
        "lp_calls": lp_calls, "trail_moves": trail_moves, "filled": filled, "no_stop": no_stop, "no_age_with_stop": no_age_with_stop,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the changed rows (default: dry run)")
    parser.add_argument("--show", default="", help="comma-separated tickers to print before/after in full")
    args = parser.parse_args()
    main(args.apply, show=tuple(t.strip().upper() for t in args.show.split(",") if t.strip()))
