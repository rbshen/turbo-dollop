"""The "Pass-family and Undervalued" state and its smoothed "since" date, over the daily signal snapshot log
(data/signal_snapshot_data.py). Pure, no I/O. docs/specs/stuck-check.md, "Daily snapshot log".

The state is flappy (the stored Valuation verdict changes for 11-14% of tickers a day, docs/why-stuck-panel-investigation-2026-10-09.md),
so a naive "first became" date would reset constantly. The since-date therefore resets only after `smoothing_days` CONSECUTIVE TRADING
DAYS out of the state (Settings > Why might it be stuck? > Time-stop smoothing). Nothing reads it yet: no UI, feeds no score.
"""

from collections.abc import Collection, Iterable
from datetime import date

PASS_FAMILY = frozenset({"Strong Pass", "Pass", "Pass with caution"})
UNDERVALUED = "undervalued"


def is_good_and_undervalued(overall_verdict: str | None, valuation_verdict: str | None) -> bool:
    """Pass-family Overall (stored keys: Strong Pass / Pass / Pass with caution) AND a stored Valuation verdict of undervalued."""
    return overall_verdict in PASS_FAMILY and valuation_verdict == UNDERVALUED


def good_and_undervalued_since(
    days: Iterable[tuple[date, bool]], smoothing_days: int, trading_days: Collection[date] | None = None
) -> date | None:
    """The date the current smoothed run of the state began, or None when the ticker is not in the state.

    `days` are (snapshot date, in_state) pairs in any order. Only snapshots dated on a trading day count (`trading_days`; None means
    Monday to Friday): a weekend or holiday snapshot repeats the previous session's values and is neither evidence of entering nor of
    leaving. The run starts on the first in-state trading day; it survives any run of fewer than `smoothing_days` consecutive out-of-state
    trading-day snapshots, and ends on the `smoothing_days`-th. A missing snapshot is not an out-of-state day. If the state began before
    the log did, the date is the first logged day (a lower bound)."""
    if smoothing_days < 1:
        raise ValueError("smoothing_days must be at least 1")
    is_trading_day = (lambda d: d in trading_days) if trading_days is not None else (lambda d: d.weekday() < 5)
    since: date | None = None
    out_streak = 0
    for day, in_state in sorted({d: s for d, s in days}.items()):
        if not is_trading_day(day):
            continue
        if in_state:
            if since is None:
                since = day
            out_streak = 0
        elif since is not None:
            out_streak += 1
            if out_streak >= smoothing_days:
                since, out_streak = None, 0
    return since
