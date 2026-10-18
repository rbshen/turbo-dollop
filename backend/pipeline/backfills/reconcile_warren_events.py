"""One-time cleanup (and dry run) of the Warren event log: reconcile every monitored ticker's stored WarrenSignalEvent rows at or after the
write gate with the arrows today's replay produces (docs/specs/warren-signals-page.md, "Event log reconcile"). The nightly Warren job does the
same reconcile for each ticker it computes; this script exists to run it once over all tickers on demand, and to preview it.

Default = DRY RUN: reads the cached 60m bars only (no FMP call, no top-up, exactly the slice the nightly job reads: the last 730 days), never
runs init_db and writes nothing. It prints, per ticker, the stored events it would delete and the replay arrows it would add, then the
consumer changes (what each reader of the log would show after), and lists tickers whose replay yields nothing or that were refused.

--apply deletes and inserts for real (the same reconcile as the nightly, events only: it does not rewrite the latest-state rows) and then
refreshes the Warren fields of TickerScore / EtfScreenerRow for the changed tickers. Back up the events first (the plan in the spec: a copy of
the WarrenSignalEvent table, not of the whole database).

Run (writes nothing):
    uv run python -m pipeline.backfills.reconcile_warren_events [--show META,INTC]
Run for real:
    uv run python -m pipeline.backfills.reconcile_warren_events --apply
"""

import argparse
import logging
import time
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from analysis.warren_signal.state_machine import UP_KINDS
from clients.shared_bars_cache import INTRADAY_INTERVAL, _eastern_today, _load_frames, _most_recent_completed_trading_date
from core.db import engine
from core.models import EtfScreenerRow, OpportunityDailyFlag, TickerScore, WarrenSignalEvent
from data.opportunity_data import _signal_window_start
from data.warren_signal_data import (
    EventReconcile,
    apply_warren_event_reconcile,
    last_buy_signal_fired_at,
    plan_warren_event_reconcile,
    refresh_warren_score_fields,
)
from data.watchlists import list_monitored_tickers
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS
from scoring.opportunity_rules import B3_WARREN_KINDS

logger = logging.getLogger(__name__)


def nightly_bars_start(now: datetime | None = None) -> date:
    """The first date of the bars the nightly job hands the writer: get_or_fetch_bars_batch's own trim, `lookback_days` calendar days
    including today (Eastern)."""
    return _eastern_today(now or datetime.now(timezone.utc)) - timedelta(days=LOOKBACK_DAYS - 1)


def consumer_changes(session: Session, plans: list[EventReconcile], as_of: date) -> list[dict]:
    """For every ticker whose reconcile changes events: what each reader of the log shows now and after the reconcile (pure reads).

    - last_buy: `warren_last_buy_fired_at` = the newest Blue/Yellow/Gray Up in the log (what TickerScore / EtfScreenerRow hold, refreshed
      from the log); `score_row` / `etf_row` are the stored copies today.
    - b3: the weekly Opportunities B3 rule's "fired": a Blue or Yellow Up dated in the last 10 sessions up to `as_of`.
    - markers: the daily-chart Warren markers, one per (day, kind) (a second event of the same kind on one day collapses into the first).
    - d1_flags: stored OpportunityDailyFlag rows (D1) dated on a day whose up event is deleted: history is not rewritten, only counted.
    """
    start = datetime.combine(_signal_window_start(as_of), datetime.min.time())
    end = datetime.combine(as_of + timedelta(days=1), datetime.min.time())
    out = []
    for plan in plans:
        if not plan.changed:
            continue
        stored = [(e.signal_kind, e.fired_at) for e in session.exec(select(WarrenSignalEvent).where(WarrenSignalEvent.ticker == plan.ticker)).all()]
        after = sorted((set(stored) - set(plan.deleted)) | set(plan.added), key=lambda k: (k[1], k[0]))
        ups_now = [f for k, f in stored if k in UP_KINDS]
        ups_after = [f for k, f in after if k in UP_KINDS]
        score = session.get(TickerScore, plan.ticker)
        etf = session.get(EtfScreenerRow, plan.ticker)
        b3_now = any(k in B3_WARREN_KINDS and start <= f < end for k, f in stored)
        b3_after = any(k in B3_WARREN_KINDS and start <= f < end for k, f in after)
        markers_now = {(f.date(), k) for k, f in stored}
        markers_after = {(f.date(), k) for k, f in after}
        dead_days = {f.date() for k, f in plan.deleted if k in B3_WARREN_KINDS}
        d1 = 0
        if dead_days:
            d1 = len(session.exec(select(OpportunityDailyFlag).where(OpportunityDailyFlag.ticker == plan.ticker, OpportunityDailyFlag.flag_date.in_(dead_days))).all())
        out.append({
            "ticker": plan.ticker,
            "last_buy_now": max(ups_now) if ups_now else None, "last_buy_after": max(ups_after) if ups_after else None,
            "score_row": score.warren_last_buy_fired_at if score else "no row", "etf_row": etf.warren_last_buy_fired_at if etf else "no row",
            "b3_now": b3_now, "b3_after": b3_after,
            "markers_removed": sorted(markers_now - markers_after), "markers_added": sorted(markers_after - markers_now),
            "d1_flags_on_deleted_days": d1,
        })
    return out


def main(apply: bool = False, show: tuple[str, ...] = ()) -> dict:
    started = time.monotonic()
    start = nightly_bars_start()
    with Session(engine) as session:
        tickers, _ = list_monitored_tickers(session)
        frames = _load_frames(session, tickers, INTRADAY_INTERVAL, start)
    plans: list[EventReconcile] = []
    no_bars: list[str] = []
    failed: list[tuple[str, str]] = []
    for ticker in sorted(tickers):
        bars = frames.get(ticker)
        if bars is None or bars.empty:
            no_bars.append(ticker)
            continue
        try:
            plans.append(apply_warren_event_reconcile(ticker, bars) if apply else plan_warren_event_reconcile(ticker, bars))
        except Exception as exc:  # noqa: BLE001 -- one bad ticker never stops the run; its events are left as they are
            failed.append((ticker, str(exc)))
    changed = [p for p in plans if p.changed]
    skipped = [p for p in plans if p.skipped]
    added = sum(len(p.added) for p in plans)
    deleted = sum(len(p.deleted) for p in plans)
    print(f"{'APPLIED' if apply else 'DRY RUN'}: {len(tickers)} monitored tickers, bars from {start}; {len(changed)} tickers change; {deleted} events deleted, {added} added; "
          f"{sum(p.unchanged for p in plans)} matching events untouched; {len(skipped)} refused; {len(no_bars)} without bars; {len(failed)} failed")
    for p in changed:
        print(f"  {p.ticker}: -{len(p.deleted)} +{len(p.added)}")
        for k, f in p.deleted:
            print(f"      delete {k:12} {f:%Y-%m-%d %H:%M}")
        for k, f in p.added:
            print(f"      add    {k:12} {f:%Y-%m-%d %H:%M}")
    for p in plans:
        if p.ticker in show and not p.changed:
            print(f"  SHOW {p.ticker}: nothing to change ({p.unchanged} matching events)")
    for p in skipped:
        print(f"  REFUSED {p.ticker}: {p.skipped}")
    for t in no_bars:
        print(f"  NO BARS {t}: events left as they are")
    for t, why in failed:
        print(f"  FAILED {t}: {why}")
    with Session(engine) as session:
        changes = consumer_changes(session, plans, _most_recent_completed_trading_date()) if not apply else []
    if changes:
        print("consumer changes (dry run):")
        for c in changes:
            moved = c["last_buy_now"] != c["last_buy_after"]
            print(f"  {c['ticker']}: warren_last_buy_fired_at {c['last_buy_now']} -> {c['last_buy_after']}"
                  f" (TickerScore {c['score_row']}, ETF row {c['etf_row']}){' CHANGES' if moved else ''}; B3 fired {c['b3_now']} -> {c['b3_after']}"
                  f"{' CHANGES' if c['b3_now'] != c['b3_after'] else ''}; chart markers removed {len(c['markers_removed'])} added {len(c['markers_added'])};"
                  f" D1 flags on deleted days {c['d1_flags_on_deleted_days']}")
    refreshed = 0
    if apply and changed:
        refreshed = refresh_warren_score_fields([p.ticker for p in changed])
        print(f"refreshed {refreshed} TickerScore / EtfScreenerRow rows")
    print(f"{time.monotonic() - started:.1f}s")
    return {"plans": plans, "changed": [p.ticker for p in changed], "added": added, "deleted": deleted, "skipped": [p.ticker for p in skipped],
            "no_bars": no_bars, "failed": failed, "consumer_changes": changes, "refreshed": refreshed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="delete and insert for real (default: dry run)")
    parser.add_argument("--show", default="", help="comma-separated tickers to mention even when nothing changes")
    args = parser.parse_args()
    main(args.apply, show=tuple(t.strip().upper() for t in args.show.split(",") if t.strip()))
