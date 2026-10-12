"""Orchestration of the daily opportunity flags (Phase 2b v1): for the names of the LATEST weekly opportunity list, look for the three
triggers of scoring/opportunity_triggers.py on the newest completed session and store each one found as an OpportunityDailyFlag, with one
OpportunityDailyRun row per night recording what could NOT be judged. Spec: docs/specs/opportunities.md, "Daily flags (Phase 2b v1)".
Entry point: pipeline/opportunity_daily_flags.py (built and run by hand; not in crontab.txt).

STORED DATA ONLY: no FMP call (the bars cache is read, never fetched). Writes only OpportunityDailyFlag and OpportunityDailyRun.
Memory stays flat: the daily bars of the watched names are read in chunks of CHUNK_SIZE and only the session closes are kept.

The cohort rule. A flag on session S attaches to the LATEST weekly run whose as-of date is BEFORE S, and only to a ticker that run LISTS
(the pool is never flagged). So on a Saturday morning (the planned slot is 03:45 UTC, before the 04:00 weekly job) Friday's signals count
against the PREVIOUS list, and Friday's own signals never count against the list built as of Friday (its B3 rule already read them). One
flag per (list as-of date, ticker, trigger): the first session a name qualified.

Not covered vs incomplete vs no flag -- three different things, kept apart so a scorecard's denominator stays honest:
- not covered: D1 needs the Warren / BB+RSI jobs to have looked at the name, and they run only for the monitored watchlists; any other name is
  stored as not covered for D1 (even if an event row happens to exist). Never "no flag".
- incomplete: the trigger could not be judged for the name tonight -- an upstream job of that night did not succeed, the name has no final bar
  for the session, the stage row is not as of the session, or the bars failed to read. Stored with its reason, never "no flag".
- no flag: judged, and the trigger did not fire. Not stored at all.

Missed nights. The event trigger (D1) catches up: every session since the job's last-seen SPY bar is evaluated, each against its own cohort.
The stage-based triggers (D2, D3) read TrendAnalysis, which holds the latest row only, so they cannot be rebuilt for a past session: they are
judged only on the newest completed session, and every skipped session (and an --as-of that is not the newest) is recorded as a GAP.

Lookahead guards: D1 uses the event row's `created_at` (it must be at or before the open of the session after the event's own session) and an
event dated on or before the list's as-of date can never count; the closes and bars used are completed bars only (the bars cache's own
provisional-bar test, the same one the weekly gate and the outcome updater use); the stage inputs are copied into the flag when observed and
never rebuilt.

`engine` and `list_monitored_tickers` are module-level references so tests can monkeypatch them (the per-module convention)."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.shared_bars_cache import _eastern_today
from core.db import engine
from core.models import (
    CronRunLog,
    OpportunityDailyFlag,
    OpportunityDailyRun,
    OpportunityRun,
    OpportunitySnapshotRow,
    TechnicalEntrySignalEvent,
    TrendAnalysis,
    WarrenSignalEvent,
)
from data import opportunity_outcome_data as ou
from data.watchlists import list_monitored_tickers
from scoring import opportunity_triggers as trig

logger = logging.getLogger(__name__)

KIND_WEEKLY = "weekly"
SPY = "SPY"
CHUNK_SIZE = 60  # tickers of bars held in memory at a time (the server has ~1 GB)
SPY_LOOKBACK_FLOOR_DAYS = 40  # calendar days of SPY read even on the first run, so the newest session and its neighbours are in the frame
BARS_SLACK_DAYS = 10

UP_STATUS_SUCCESS = "success"
UP_STATUS_MISSING = "missing"


@dataclass
class TriggerCount:
    evaluated: int = 0  # names judged (not covered / incomplete names are not)
    flagged: int = 0  # new flags written (or that would be, on a dry run)
    already_flagged: int = 0  # names that already carry this trigger on this list: not re-judged
    not_covered: int = 0
    incomplete: int = 0

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("evaluated", "flagged", "already_flagged", "not_covered", "incomplete")}


@dataclass
class DailyResult:
    status: str  # "noop" | "success" | "dry_run"
    reason: str = ""  # why a no-op
    sessions: list[date] = field(default_factory=list)
    session_date: date | None = None  # the newest session evaluated
    spy_last_bar_date: date | None = None
    list_as_of_date: date | None = None  # the weekly list the newest session was judged against
    watched: int = 0  # listed rows of that list
    attempted: int = 0  # tickers whose bars the run tried to read (the denominator of the failure threshold)
    failed: dict[str, str] = field(default_factory=dict)  # ticker -> why its bars could not be read
    flags_created: int = 0
    counts: dict[str, TriggerCount] = field(default_factory=dict)
    new_flags: list[dict] = field(default_factory=list)  # what was (or on a dry run would be) written
    not_covered: dict[str, list[str]] = field(default_factory=dict)
    incomplete: dict[str, dict[str, str]] = field(default_factory=dict)
    gaps: list[dict] = field(default_factory=list)
    upstream: dict[str, dict[str, str]] = field(default_factory=dict)  # session -> job -> status

    def message(self) -> str:
        if self.status == "noop":
            return f"no-op: {self.reason}"
        per = ", ".join(f"{t.split('.')[0]} {self.counts[t].flagged}" for t in trig.TRIGGER_IDS if t in self.counts)
        n_nc = len({t for names in self.not_covered.values() for t in names})
        n_inc = sum(len(v) for v in self.incomplete.values())
        tail = f", {len(self.failed)} ticker(s) failed to read" if self.failed else ""
        return (
            f"{self.status}: session {self.session_date} against the list of {self.list_as_of_date}, {self.watched} watched; "
            f"{self.flags_created} flag(s) ({per}); not covered {n_nc}, incomplete {n_inc}, gaps {len(self.gaps)}{tail}"
        )


# --- helpers ----------------------------------------------------------------------------------------------------------------------


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo is not None else moment


def session_window(day: date) -> tuple[datetime, datetime | None, datetime | None]:
    """(close of `day`, open of the NEXT session, close of the next session), all naive UTC, from the XNYS calendar. The next session's
    times are None when the calendar knows none; a calendar that cannot be used at all falls back to 20:00 UTC the same day (the latest
    possible close) and no next-session times."""
    try:
        from helpers.trading_calendar import xnys_sessions

        sessions = xnys_sessions(day - timedelta(days=1), day + timedelta(days=14))
        by_day = {d: (o, c) for d, o, c in sessions}
        following = [(d, o, c) for d, o, c in sessions if d > day]
        close = _naive_utc(by_day[day][1]) if day in by_day else datetime.combine(day, time(20, 0))
        if following:
            _d, nxt_open, nxt_close = following[0]
            return close, _naive_utc(nxt_open), _naive_utc(nxt_close)
        return close, None, None
    except Exception:  # noqa: BLE001 -- a calendar problem must not stop the run
        logger.warning("Daily flags: XNYS calendar unavailable, using fallback session times.")
        return datetime.combine(day, time(20, 0)), None, None


def _upstream_status(session: Session, day: date, now_naive: datetime) -> dict[str, str]:
    """{job: status} for the three upstream nightly jobs on the night(s) after `day`'s close: 'success' if any run in that window succeeded,
    else the most recent run's status, else 'missing'. The window runs from the session's close to the next session's close (open-ended
    when that is still in the future)."""
    close, _open, next_close = session_window(day)
    out: dict[str, str] = {}
    for job in trig.UPSTREAM_JOBS:
        stmt = select(CronRunLog).where(CronRunLog.job_name == job, CronRunLog.started_at >= close)
        if next_close is not None and next_close <= now_naive:
            stmt = stmt.where(CronRunLog.started_at < next_close)
        rows = session.exec(stmt.order_by(CronRunLog.started_at)).all()
        if any(r.status == UP_STATUS_SUCCESS for r in rows):
            out[job] = UP_STATUS_SUCCESS
        else:
            out[job] = rows[-1].status if rows else UP_STATUS_MISSING
    return out


def _last_seen_spy_bar(session: Session) -> date | None:
    row = session.exec(
        select(OpportunityDailyRun).where(OpportunityDailyRun.spy_last_bar_date.is_not(None)).order_by(OpportunityDailyRun.id.desc()).limit(1)
    ).first()
    return row.spy_last_bar_date if row is not None else None


def _cohort_run(session: Session, day: date) -> OpportunityRun | None:
    """The latest weekly run with as_of strictly BEFORE the session: a session's own list never judges it."""
    return session.exec(
        select(OpportunityRun)
        .where(OpportunityRun.kind == KIND_WEEKLY, OpportunityRun.as_of_date < day)
        .order_by(OpportunityRun.as_of_date.desc())
        .limit(1)
    ).first()


def _json(text: str | None) -> dict:
    try:
        value = json.loads(text or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


# --- the run ------------------------------------------------------------------------------------------------------------------------


def run_daily(as_of: date | None = None, dry_run: bool = False, now: datetime | None = None) -> DailyResult:
    """Evaluates the triggers for the newest completed session (and any sessions missed since the last run, for D1) and writes the new
    flags. `as_of` targets one session and skips the new-SPY-bar check. `dry_run` computes the same state and writes nothing."""
    now = now or datetime.now(timezone.utc)
    now_naive = _naive_utc(now)
    result = DailyResult(status="dry_run" if dry_run else "success")

    with Session(engine) as session:
        last_seen = None if as_of is not None else _last_seen_spy_bar(session)

    spy_lookback = SPY_LOOKBACK_FLOOR_DAYS
    if last_seen is not None:
        spy_lookback = max(spy_lookback, (_eastern_today(now) - last_seen).days + BARS_SLACK_DAYS)
    spy_bars = ou._read_bars([SPY], spy_lookback, now).get(SPY)
    if spy_bars is None or spy_bars.empty:
        raise RuntimeError("no completed SPY bars in the cache: cannot build the session calendar")
    spy_dates = sorted({ts.date() for ts in spy_bars.index})
    latest = spy_dates[-1]
    result.spy_last_bar_date = latest

    if as_of is not None:
        if as_of not in spy_dates:
            raise ValueError(f"{as_of} is not a completed session in the cached SPY bars (newest {latest})")
        sessions = [as_of]
    elif last_seen is not None and latest <= last_seen:
        result.status, result.reason = "noop", f"SPY has no bar newer than {last_seen} (the last run's)"
        return result
    elif last_seen is None:
        sessions = [latest]
    else:
        sessions = [d for d in spy_dates if d > last_seen]
    result.sessions = sessions
    result.session_date = sessions[-1]

    # --- cohorts, watched names, upstream status ---------------------------------------------------------------------------------
    with Session(engine) as session:
        cohorts: dict[date, tuple[OpportunityRun, list[OpportunitySnapshotRow]]] = {}
        for day in sessions:
            run = _cohort_run(session, day)
            if run is None:
                continue
            if run.id not in {r.id for r, _ in cohorts.values()}:
                rows = list(session.exec(select(OpportunitySnapshotRow).where(OpportunitySnapshotRow.run_id == run.id).order_by(OpportunitySnapshotRow.list_order)).all())
            else:
                rows = next(rws for r, rws in cohorts.values() if r.id == run.id)
            cohorts[day] = (run, rows)
        monitored = set(list_monitored_tickers(session)[0])
        upstream = {day: _upstream_status(session, day, now_naive) for day in sessions}
        existing_flags = {
            (f.list_as_of_date, f.ticker, f.trigger_id)
            for f in session.exec(
                select(OpportunityDailyFlag).where(OpportunityDailyFlag.list_as_of_date.in_({r.as_of_date for r, _ in cohorts.values()}))
            ).all()
        } if cohorts else set()
        session.expunge_all()
    result.upstream = {d.isoformat(): st for d, st in upstream.items()}
    for trigger_id in trig.TRIGGER_IDS:
        result.counts[trigger_id] = TriggerCount()

    if not cohorts:
        result.status, result.reason = "noop", f"no weekly opportunity list dated before {sessions[0]}"
        return result
    final_day = sessions[-1]
    if final_day in cohorts:
        result.list_as_of_date = cohorts[final_day][0].as_of_date
        result.watched = len(cohorts[final_day][1])

    tickers = sorted({row.ticker for _, rows in cohorts.values() for row in rows})
    result.attempted = len(tickers)

    # --- bars: the final close of each session, chunk by chunk -------------------------------------------------------------------
    closes: dict[tuple[str, date], float] = {}
    lookback = (_eastern_today(now) - sessions[0]).days + BARS_SLACK_DAYS
    wanted = set(sessions)
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i : i + CHUNK_SIZE]
        try:
            frames = ou._read_bars(chunk, lookback, now)
        except Exception as exc:  # noqa: BLE001 -- a bad chunk leaves its names "incomplete"; the other chunks still run
            logger.exception("Daily flags: reading the bars of %s failed.", chunk)
            for t in chunk:
                result.failed[t] = f"bars read failed: {exc}"
            continue
        for t, frame in frames.items():
            for ts, close in frame["close"].items():
                if ts.date() in wanted and close == close and close > 0:
                    closes[(t, ts.date())] = float(close)
        del frames

    # --- D1 inputs: the stored events in the window -----------------------------------------------------------------------------
    events = _load_events(sessions, tickers)
    # --- D2 / D3 inputs: tonight's stage rows -----------------------------------------------------------------------------------
    with Session(engine) as session:
        stage_rows = {r.ticker: r for r in session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker.in_(tickers))).all()}
        session.expunge_all()

    new_rows: list[dict] = []

    def mark_incomplete(trigger_id: str, ticker: str, reason: str) -> None:
        result.incomplete.setdefault(trigger_id, {})[ticker] = reason
        result.counts[trigger_id].incomplete += 1

    for day in sessions:
        if day not in cohorts:
            continue
        run, rows = cohorts[day]
        status = upstream[day]
        close_utc, next_open, _next_close = session_window(day)
        state_ok_session = day == final_day and day == latest  # D2 / D3 can only be judged on the newest completed session
        if not state_ok_session:
            for trigger_id in (trig.TRIGGER_D2, trig.TRIGGER_D3):
                if any(trigger_id in trig.applicable_triggers(r.list_name, _json(r.tags_json)) for r in rows):
                    result.gaps.append({"type": "state_trigger_gap", "trigger": trigger_id, "session": day.isoformat(), "list_as_of_date": run.as_of_date.isoformat()})
        for row in rows:
            tags = _json(row.tags_json)
            inputs = _json(row.inputs_json)
            for trigger_id in trig.applicable_triggers(row.list_name, tags):
                key = (run.as_of_date, row.ticker, trigger_id)
                count = result.counts[trigger_id]
                if key in existing_flags:
                    count.already_flagged += 1
                    continue
                is_state = trigger_id in (trig.TRIGGER_D2, trig.TRIGGER_D3)
                if is_state and not state_ok_session:
                    continue  # recorded as a gap above
                if trigger_id == trig.TRIGGER_D1 and row.ticker not in monitored:
                    result.not_covered.setdefault(trigger_id, [])
                    if row.ticker not in result.not_covered[trigger_id]:
                        result.not_covered[trigger_id].append(row.ticker)
                        count.not_covered += 1
                    continue
                bad = [j for j in trig.TRIGGER_JOBS[trigger_id] if status.get(j) != UP_STATUS_SUCCESS]
                if bad:
                    mark_incomplete(trigger_id, row.ticker, f"{trig.INCOMPLETE_UPSTREAM}: " + ", ".join(f"{j.split('.')[-1]}={status.get(j)}" for j in bad))
                    continue
                if row.ticker in result.failed:
                    mark_incomplete(trigger_id, row.ticker, trig.INCOMPLETE_BARS_READ)
                    continue
                close = closes.get((row.ticker, day))
                if close is None:
                    mark_incomplete(trigger_id, row.ticker, trig.INCOMPLETE_NO_BAR)
                    continue

                evidence: dict | None
                if trigger_id == trig.TRIGGER_D1:
                    evidence = _judge_d1(events.get((row.ticker, day), []), day, next_open)
                    late = [e for e in events.get((row.ticker, day), []) if not trig.event_is_knowable(day, e["created_at"], next_open)]
                    if evidence is None and late:
                        result.gaps.append({"type": "late_event", "ticker": row.ticker, "session": day.isoformat(), "created_at": late[0]["created_at"].isoformat()})
                else:
                    stage = stage_rows.get(row.ticker)
                    if stage is None or stage.weinstein_stage is None:
                        mark_incomplete(trigger_id, row.ticker, trig.INCOMPLETE_NO_STAGE)
                        continue
                    if stage.bars_as_of != day:
                        mark_incomplete(trigger_id, row.ticker, f"{trig.INCOMPLETE_STALE_STAGE} ({stage.bars_as_of})")
                        continue
                    evidence = _judge_stage_trigger(trigger_id, row, inputs, stage)
                count.evaluated += 1
                if evidence is None:
                    continue
                count.flagged += 1
                new_rows.append(
                    {
                        "list_as_of_date": run.as_of_date, "ticker": row.ticker, "trigger_id": trigger_id, "trigger_version": trig.TRIGGERS_VERSION,
                        "list_name": row.list_name, "tier": row.tier, "flag_date": day, "observed_at": now_naive, "close": close, "sector": row.sector,
                        "inputs_json": json.dumps(_frozen_inputs(row, tags, inputs, evidence), default=str),
                    }
                )
                existing_flags.add(key)

    result.new_flags = new_rows
    result.flags_created = len(new_rows)
    if not dry_run and new_rows:
        with Session(engine) as session:
            for values in new_rows:
                session.execute(
                    sqlite_insert(OpportunityDailyFlag).values(**values).on_conflict_do_nothing(index_elements=["list_as_of_date", "ticker", "trigger_id"])
                )
            session.commit()
    return result


def _load_events(sessions: list[date], tickers: list[str]) -> dict[tuple[str, date], list[dict]]:
    """The stored up-signal events of the watched names dated within the evaluated sessions, grouped by (ticker, session date)."""
    start = datetime.combine(min(sessions), time.min)
    end = datetime.combine(max(sessions) + timedelta(days=1), time.min)
    out: dict[tuple[str, date], list[dict]] = {}
    with Session(engine) as session:
        warren = session.exec(
            select(WarrenSignalEvent).where(
                WarrenSignalEvent.ticker.in_(tickers), WarrenSignalEvent.signal_kind.in_(trig.D1_WARREN_KINDS),
                WarrenSignalEvent.fired_at >= start, WarrenSignalEvent.fired_at < end,
            )
        ).all()
        bb = session.exec(
            select(TechnicalEntrySignalEvent).where(
                TechnicalEntrySignalEvent.ticker.in_(tickers), TechnicalEntrySignalEvent.signal_type == trig.D1_BB_RSI,
                TechnicalEntrySignalEvent.fired_at >= start, TechnicalEntrySignalEvent.fired_at < end,
            )
        ).all()
        for e in warren:
            out.setdefault((e.ticker, e.fired_at.date()), []).append(
                {"source": trig.SOURCE_WARREN, "kind": e.signal_kind, "fired_at": e.fired_at, "created_at": e.created_at}
            )
        for e in bb:
            out.setdefault((e.ticker, e.fired_at.date()), []).append(
                {"source": trig.SOURCE_BB_RSI, "kind": "bb_rsi", "fired_at": e.fired_at, "created_at": e.created_at}
            )
    return out


def _judge_d1(events: list[dict], day: date, next_open: datetime | None) -> dict | None:
    """The knowable events of the session, or None when there is none."""
    knowable = [e for e in events if trig.event_is_knowable(day, e["created_at"], next_open)]
    if not knowable:
        return None
    knowable.sort(key=lambda e: (e["fired_at"], e["source"]))
    return {"events": [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in e.items()} for e in knowable]}


def _judge_stage_trigger(trigger_id: str, row: OpportunitySnapshotRow, inputs: dict, stage: TrendAnalysis) -> dict | None:
    observed = {
        "stage": stage.weinstein_stage, "pending_direction": stage.weinstein_pending_direction, "vs_ma_pct": stage.weinstein_vs_ma_pct,
        "ma_slope_pct": stage.weinstein_ma_slope_pct, "mansfield_rs": stage.weinstein_mansfield_rs, "bars_as_of": stage.bars_as_of,
        "stage_row_computed_at": stage.computed_at,
    }
    if trigger_id == trig.TRIGGER_D2:
        why = trig.stage_upgrade(row.weinstein_stage, inputs.get("pending_direction"), stage.weinstein_stage, stage.weinstein_pending_direction)
        return {"upgrade": why, "observed": observed} if why else None
    if trig.pullback_to_ma(stage.weinstein_stage, stage.weinstein_vs_ma_pct, stage.weinstein_ma_slope_pct, stage.weinstein_mansfield_rs):
        return {"max_vs_ma_pct": trig.PULLBACK_MAX_VS_MA_PCT, "observed": observed}
    return None


def _frozen_inputs(row: OpportunitySnapshotRow, tags: dict, inputs: dict, evidence: dict) -> dict:
    """What the flag was judged on, frozen: the list row's own figures and what the trigger saw."""
    return {
        "trigger_version": trig.TRIGGERS_VERSION,
        "list_row": {
            "weinstein_stage": row.weinstein_stage, "pending_direction": inputs.get("pending_direction"), "vs_ma_pct": row.vs_ma_pct,
            "ma_slope_pct": row.ma_slope_pct, "mansfield_rs": row.mansfield_rs, "close": row.close, "weeks_in_advance": inputs.get("weeks_in_advance"),
            "deep_pullback": bool(tags.get("deep_pullback")), "already_at_ma_on_list": (row.vs_ma_pct is not None and row.vs_ma_pct <= trig.PULLBACK_MAX_VS_MA_PCT),
        },
        "evidence": evidence,
    }


# --- the heartbeat-style log -------------------------------------------------------------------------------------------------------


def start_log(now: datetime | None = None) -> int | None:
    """Opens an OpportunityDailyRun row ("running"); None if the log write itself fails (it must never stop the run)."""
    try:
        with Session(engine) as session:
            row = OpportunityDailyRun(started_at=now or datetime.now(), status="running")
            session.add(row)
            session.commit()
            return row.id
    except Exception:  # noqa: BLE001
        logger.warning("Daily flags: could not write the start of the log row.", exc_info=True)
        return None


def finish_log(log_id: int | None, status: str, message: str, result: DailyResult | None = None) -> None:
    """Closes the row. A failed run stores no SPY date, so the next run is not short-circuited by it."""
    if log_id is None:
        return
    try:
        with Session(engine) as session:
            row = session.get(OpportunityDailyRun, log_id)
            if row is None:
                return
            row.finished_at, row.status, row.message = datetime.now(), status, message[:1000]
            if result is not None:
                row.session_date = result.session_date
                row.spy_last_bar_date = result.spy_last_bar_date if status in ("success", "noop") else None
                row.list_as_of_date = result.list_as_of_date
                row.sessions_json = json.dumps([d.isoformat() for d in result.sessions])
                row.upstream_json = json.dumps(result.upstream)
                row.watched = result.watched
                row.flags_created = result.flags_created
                row.not_covered_json = json.dumps(result.not_covered)
                row.incomplete_json = json.dumps(result.incomplete)
                row.gaps_json = json.dumps(result.gaps)
                row.summary_json = json.dumps({"counts": {t: c.as_dict() for t, c in result.counts.items()}, "failed": result.failed})
            session.add(row)
            session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Daily flags: could not write the end of the log row.", exc_info=True)
