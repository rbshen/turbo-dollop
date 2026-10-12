"""Pure outcome engine for the opportunity agent: how a LISTED snapshot row did over the next 5 / 10 / 20 / 60 sessions. No DB, no
I/O, no clock -- bars in, one `HorizonOutcome` per horizon out (pipeline/opportunity_outcome_update.py does the reading and the
upserting). Spec: docs/specs/opportunities.md, "Outcome tracking".

Conventions (all agreed, each one constant or one line):
- PRICE-ONLY returns (open/close as stored), never dividend-adjusted.
- SPY's bar dates are the session calendar, so holidays and half-days need no calendar of their own. The sessions are the SPY
  dates AFTER the as-of date: S[0] is the entry bar, S[N] the horizon-N bar.
- Entry is the OPEN of S[0]. Horizon N exits at the CLOSE of S[N] (the Nth bar after the entry bar). The window for the stop, the
  worst/best move and the drawdown is S[0]..S[N]: the entry bar is bar 1 of the position.
- Stop: intraday, STOP_PCT below entry. A bar's low <= entry x (1 - STOP_PCT) is a hit, the entry bar's own low included. A gap
  below the stop fills at the open: stop_fill_return = min(-STOP_PCT, open / entry - 1) on the stop bar. `forward_return` is
  buy-and-hold; the stop is recorded beside it, never applied to it.
- A stop is path-dependent and final: it is reported as soon as the window contains it, on a still-`pending` row too.
- `pending` until the horizon bar exists. `complete` once the ticker has the entry bar and the horizon bar. `censored` when the
  ticker is missing either and SPY is already more than CENSOR_GRACE_SESSIONS sessions past the horizon date (delisted, acquired,
  left the universe, a data hole): the row keeps the return to the LAST AVAILABLE bar as a sensitivity line, and is excluded from
  means by whoever reads it (the updater re-evaluates it for CENSOR_REVIVE_DAYS, then freezes it). A ticker with no entry bar more than CENSOR_GRACE_SESSIONS sessions after the entry date is censored
  at every horizon at once (nothing can be priced).
- Benchmarks: SPY (headline) and the ticker's sector ETF, each entry open to the same exit date's close. No sector ETF (an ETF, an
  unmapped sector) -> the sector fields are None and the row compares against SPY only.
- `entry_gap_pct` = entry open / the frozen as-of close - 1; `entry_gap_flag` when its size passes ENTRY_GAP_FLAG_PCT.

Bar frames: a DatetimeIndex (date-like, any time-of-day) with lowercase `open`, `high`, `low`, `close` columns."""

from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
import pandas as pd

HORIZONS: tuple[int, ...] = (5, 10, 20, 60)
STOP_PCT = 0.10
ENTRY_GAP_FLAG_PCT = 0.25
CENSOR_GRACE_SESSIONS = 3
# A censored row stays revivable this many calendar days from the day it was FIRST censored (OpportunityOutcome.first_censored_at):
# the updater re-evaluates it every run, and bars that were only late (a price-data hole, not a delisting) revive it. After that it is
# frozen like a complete row.
CENSOR_REVIVE_DAYS = 14
_STOP_EPSILON = 1e-9  # a low that lands on the stop price to the last float digit still counts as a hit

PENDING, COMPLETE, CENSORED = "pending", "complete", "censored"
REASON_DELISTED, REASON_LEFT_UNIVERSE, REASON_STALE = "delisted", "left_universe", "stale"


@dataclass
class HorizonOutcome:
    horizon: int
    status: str
    censor_reason: str | None = None
    entry_date: date | None = None
    entry_open: float | None = None
    exit_date: date | None = None
    exit_close: float | None = None
    forward_return: float | None = None
    spy_return: float | None = None
    excess_vs_spy: float | None = None
    sector_etf: str | None = None
    sector_return: float | None = None
    excess_vs_sector: float | None = None
    worst_move: float | None = None
    best_move: float | None = None
    max_drawdown: float | None = None
    stop_hit: bool = False
    stop_date: date | None = None
    stop_fill_return: float | None = None
    entry_gap_pct: float | None = None
    entry_gap_flag: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _by_date(frame: pd.DataFrame | None) -> pd.DataFrame:
    """The frame re-indexed by plain calendar date (sorted, one row per date, the last write wins); empty when there is none."""
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close"], index=pd.DatetimeIndex([]))
    out = frame[["open", "high", "low", "close"]].astype(float)
    out.index = pd.DatetimeIndex(out.index).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _num(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _censor_reason(delisted: bool, in_universe: bool) -> str:
    if delisted:
        return REASON_DELISTED
    if not in_universe:
        return REASON_LEFT_UNIVERSE
    return REASON_STALE


def _benchmark_return(bars: pd.DataFrame, entry_ts: pd.Timestamp, exit_ts: pd.Timestamp) -> float | None:
    """Entry-date open to exit-date close of a benchmark; None when either bar is missing."""
    if entry_ts not in bars.index or exit_ts not in bars.index:
        return None
    entry, exit_ = _num(bars.at[entry_ts, "open"]), _num(bars.at[exit_ts, "close"])
    if entry is None or exit_ is None or entry <= 0:
        return None
    return exit_ / entry - 1.0


def compute_outcomes(
    *,
    as_of: date,
    as_of_close: float | None,
    ticker_bars: pd.DataFrame | None,
    spy_bars: pd.DataFrame | None,
    sector_bars: pd.DataFrame | None = None,
    sector_etf: str | None = None,
    delisted: bool = False,
    in_universe: bool = True,
    horizons: tuple[int, ...] = HORIZONS,
) -> list[HorizonOutcome]:
    """One HorizonOutcome per horizon for a ticker listed as of `as_of` (whose frozen close was `as_of_close`).

    `delisted` / `in_universe` only pick the `censor_reason` of a row that ends up censored. Deterministic: the same bars always
    give the same rows, so recomputing a pending row can only move it forward."""
    spy = _by_date(spy_bars)
    sessions = [ts for ts in spy.index if ts.date() > as_of]
    if not sessions:
        return [HorizonOutcome(horizon=n, status=PENDING, sector_etf=sector_etf) for n in horizons]

    bars = _by_date(ticker_bars)
    sector = _by_date(sector_bars) if sector_etf else None
    entry_ts = sessions[0]
    reason = _censor_reason(delisted, in_universe)

    entry_open = _num(bars.at[entry_ts, "open"]) if entry_ts in bars.index else None
    if entry_open is not None and entry_open <= 0:
        entry_open = None
    # nothing can be priced when the entry bar is missing and SPY is already more than the grace past it
    entry_lost = entry_open is None and len(sessions) - 1 > CENSOR_GRACE_SESSIONS

    gap_pct = None
    if entry_open is not None and as_of_close is not None and as_of_close > 0:
        gap_pct = entry_open / as_of_close - 1.0
    gap_flag = gap_pct is not None and abs(gap_pct) > ENTRY_GAP_FLAG_PCT

    out: list[HorizonOutcome] = []
    for n in horizons:
        base = HorizonOutcome(
            horizon=n,
            status=PENDING,
            entry_date=entry_ts.date() if entry_open is not None else None,
            entry_open=entry_open,
            sector_etf=sector_etf,
            entry_gap_pct=gap_pct,
            entry_gap_flag=gap_flag,
        )
        horizon_reached = len(sessions) > n
        past_grace = horizon_reached and len(sessions) - 1 - n > CENSOR_GRACE_SESSIONS

        if entry_open is None:
            if entry_lost or past_grace:
                base.status, base.censor_reason = CENSORED, reason
            out.append(base)
            continue

        window = bars.reindex(sessions[: n + 1])
        present = window.dropna(subset=["close"])  # the sessions the ticker actually has a bar for
        lows, highs, closes = window["low"], window["high"], present["close"]

        base.worst_move = _num(lows.min()) / entry_open - 1.0 if lows.notna().any() else None
        base.best_move = _num(highs.max()) / entry_open - 1.0 if highs.notna().any() else None
        if len(closes):
            base.max_drawdown = float((closes / closes.cummax() - 1.0).min())

        stop_price = entry_open * (1.0 - STOP_PCT)
        hits = window.index[(window["low"] <= stop_price * (1.0 + _STOP_EPSILON)).to_numpy()]
        if len(hits):
            hit = hits[0]
            gap = _num(window.at[hit, "open"])
            base.stop_hit, base.stop_date = True, hit.date()
            base.stop_fill_return = min(-STOP_PCT, gap / entry_open - 1.0) if gap is not None else -STOP_PCT

        horizon_ts = sessions[n] if horizon_reached else None
        if horizon_ts is not None and horizon_ts in present.index:
            base.status = COMPLETE
            last_ts = horizon_ts
        elif past_grace and len(present):
            base.status, base.censor_reason = CENSORED, reason
            last_ts = present.index[-1]
        else:
            out.append(base)
            continue

        base.exit_date = last_ts.date()
        base.exit_close = float(present.at[last_ts, "close"])
        base.forward_return = base.exit_close / entry_open - 1.0
        base.spy_return = _benchmark_return(spy, entry_ts, last_ts)
        if base.spy_return is not None:
            base.excess_vs_spy = base.forward_return - base.spy_return
        if sector is not None:
            base.sector_return = _benchmark_return(sector, entry_ts, last_ts)
            if base.sector_return is not None:
                base.excess_vs_sector = base.forward_return - base.sector_return
        out.append(base)
    return out


def mean_excess(outcomes: list[HorizonOutcome], horizon: int, benchmark: str = "spy") -> float | None:
    """Mean excess return over the COMPLETE rows of one horizon (censored and pending rows are excluded); None with no rows."""
    field = "excess_vs_spy" if benchmark == "spy" else "excess_vs_sector"
    values = [getattr(o, field) for o in outcomes if o.horizon == horizon and o.status == COMPLETE and getattr(o, field) is not None]
    return float(np.mean(values)) if values else None
