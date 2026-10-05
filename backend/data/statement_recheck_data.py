"""Nightly recheck of flagged statements: the live half (docs/specs/statement-data-quality.md, section 5).

Called by pipeline/nightly_fundamentals_fetch.py after its normal per-ticker pass. `helpers/statement_recheck.py`
decides WHICH tickers are flagged and due; this module spends the calls:

  scan (cache only) -> pick the due rows (oldest attempt first, at most RECHECK_MAX_CALLS_PER_NIGHT calls) ->
  per ticker refetch the three QUARTERLY statements through the production `core.cache.force_fetch` (so the history
  merge and the fetched_at stamp are exactly production's; no other cache key is touched) -> re-evaluate the rules on
  the rows now cached -> move the RecheckState.

Safety rules, each pinned by tests/test_nightly_recheck.py:
  * A fetch that is blocked (data group off, plan restriction / 402, request variant unavailable) or fails (timeout,
    429, 5xx) raises out of `force_fetch` before any write: cached rows are neither wiped nor re-stamped, and the
    attempt is NOT counted.
  * An empty or non-list answer is not written either (stricter than production, which stamps fetched_at on one).
  * Regression guard: a live payload is not written when its newest row trips a rule of that statement
    (balance sheet: debt/current-assets remap; cash flow: placeholder/scale break) that the cached newest row does not.
  * An attempt counts only when all three statements got a live answer (written, or vetoed by the guard).
  * Nothing here runs unless the caller already passed `job_skip_reason("fundamentals")`; this module adds no gate of
    its own beyond treating a blocked call as "no attempt".

The recheck only moves the three quarterly rows' fetched_at forward, after the normal pass has run. It does not touch
the earnings-aware staleness rule, and a stamp made before a new earnings cutoff still reads stale after it."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Awaitable, Callable

import httpx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from clients.fmp_client import FMPDisabledError, fmp_client
from core.cache import force_fetch
from core.models import RecheckState
from helpers import statement_recheck as sr
from helpers.ttm import TOTAL_QUARTERS_NEEDED

logger = logging.getLogger(__name__)

RECHECK_CALLS_PER_TICKER = 3  # income, balance sheet, cash flow (quarterly)
RECHECK_MAX_CALLS_PER_NIGHT = 60  # = 20 tickers

# Which rules a live payload for each statement is answerable for in the regression guard.
_BALANCE_RULES = {sr.DEBT_REMAP, sr.CURRENT_ASSETS_REMAP}
_CASH_FLOW_RULES = {sr.PLACEHOLDER_CF, sr.SCALE_BREAK}

# fetch outcome per statement
OK, GUARD, BLOCKED, ERROR, EMPTY = "ok", "guard", "blocked", "error", "empty"


class _SkipWrite(Exception):
    """Raised from inside a force_fetch fetch function to veto the write (not an httpx error: nothing catches it on
    the way out, so no row is written or re-stamped)."""


@dataclass
class RecheckSummary:
    selected: int = 0
    healed: int = 0
    healed_by_cache: int = 0
    still_flagged: int = 0
    gave_up: int = 0
    deferred: int = 0
    guard_hits: int = 0
    not_counted: int = 0  # blocked / failed / empty: no attempt recorded
    errors: int = 0  # unexpected exception while rechecking one ticker
    calls: int = 0  # live FMP calls made (blocked calls are not counted)
    scanned_flagged: int = 0
    details: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "details"}

    @property
    def active(self) -> bool:
        return any((self.selected, self.healed, self.healed_by_cache, self.gave_up, self.deferred, self.guard_hits))


def _newest_filing_dates(statements: sr.Statements) -> str:
    def first(rows: list[dict]) -> str:
        return (sr.row_filing_date(rows[0]) or "-") if rows else "-"

    return (
        f"income {first(statements.income_quarterly)}, balance {first(statements.balance_quarterly)}, "
        f"cash flow {first(statements.cash_flow_quarterly)}"
    )


def _rules(statements: sr.Statements, company_type: str | None, today: date, only: set[str]) -> set[str]:
    return set(sr.evaluate_rules(statements, company_type, today).rules) & only


def due_states(session: Session, tickers: list[str], today: date) -> list[RecheckState]:
    """Rows of `tickers` that are due tonight, oldest attempt first (never attempted first, then oldest anchor, then
    ticker)."""
    wanted = set(tickers)
    due = []
    for state in session.exec(select(RecheckState).where(RecheckState.status.in_([sr.ACTIVE, sr.CHRONIC]))).all():
        if state.ticker in wanted and sr.is_due(state, today, sr.statements_fetched_on(session, state.ticker, today)):
            due.append(state)
    due.sort(key=lambda s: (s.last_attempt_at or datetime.min, s.anchor_date, s.ticker))
    return due


async def recheck_ticker(
    engine: Engine,
    ticker: str,
    today: date,
    now: datetime,
    rescore: Callable[..., Awaitable] | None = None,
) -> tuple[RecheckSummary, str]:
    """One ticker's recheck. Returns a per-ticker summary (counts for the night) and the log line."""
    summary = RecheckSummary()
    outcome: dict[str, str] = {}
    live: dict[str, list[dict]] = {}

    with Session(engine) as session:
        state = session.get(RecheckState, ticker)
        if state is None:
            return summary, f"Statement recheck {ticker}: no RecheckState row, skipped"
        before, company_type = sr.load_cached_statements(session, ticker)
        before_rules = sr.evaluate_rules(before, company_type, today).rules
        cached_balance_trips = _rules(before, company_type, today, _BALANCE_RULES)
        cached_cash_flow_trips = _rules(before, company_type, today, _CASH_FLOW_RULES)

        def guard(kind: str, rows: list[dict]) -> str | None:
            if kind == "income":
                return None
            if kind == "balance":
                trips = _rules(before._replace(balance_quarterly=rows), company_type, today, _BALANCE_RULES) - cached_balance_trips
            else:
                trips = (
                    _rules(
                        before._replace(income_quarterly=live.get("income", before.income_quarterly), cash_flow_quarterly=rows),
                        company_type,
                        today,
                        _CASH_FLOW_RULES,
                    )
                    - cached_cash_flow_trips
                )
            return ", ".join(sorted(trips)) if trips else None

        def make_fetch(kind: str, call: Callable[[], Awaitable]):
            async def fetch():
                summary.calls += 1
                try:
                    data = await call()
                except FMPDisabledError:  # group off / variant unavailable: no network call was made
                    summary.calls -= 1
                    outcome[kind] = BLOCKED
                    raise
                except httpx.HTTPStatusError as exc:
                    outcome[kind] = BLOCKED if exc.response.status_code == 402 else ERROR
                    raise
                except httpx.HTTPError:
                    outcome[kind] = ERROR
                    raise
                rows = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
                if not rows:
                    outcome[kind] = EMPTY
                    raise _SkipWrite("empty or non-list answer")
                vetoed = guard(kind, rows)
                if vetoed:
                    outcome[kind] = GUARD
                    logger.warning(
                        "Statement recheck %s: regression guard, live %s statement not written (live newest row trips %s; cached does not)",
                        ticker,
                        kind,
                        vetoed,
                    )
                    raise _SkipWrite(f"regression guard: {vetoed}")
                live[kind] = rows
                outcome[kind] = OK
                return data

            return fetch

        plan = (
            ("income", "income_statement", lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED)),
            ("balance", "balance_sheet_statement", lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED)),
            ("cash flow", "cash_flow_statement", lambda: fmp_client.get_cash_flow_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED)),
        )
        for kind, statement_type, call in plan:
            try:
                await force_fetch(session, ticker, statement_type, "quarterly", make_fetch(kind, call))
            except _SkipWrite:
                pass
            except httpx.HTTPError as exc:  # includes FMPGroupDisabledError raised for an off group with nothing cached
                outcome.setdefault(kind, BLOCKED if isinstance(exc, FMPDisabledError) else ERROR)
            outcome.setdefault(kind, BLOCKED)  # force_fetch served the cache without calling (group not live)

        after, company_type_after = sr.load_cached_statements(session, ticker)
        after_ev = sr.evaluate_rules(after, company_type_after, today)

        counted = all(o in (OK, GUARD) for o in outcome.values())
        guarded = GUARD in outcome.values()
        state, event = sr.apply_evaluation(state, ticker, after_ev, today, now)
        if counted and event != "rearmed":
            state.attempts += 1
            state.last_attempt_at = now
            if event != "healed":
                state.last_result = "regression_guard" if guarded else "still_flagged"
        elif not counted and event != "healed":
            state.last_result = BLOCKED if BLOCKED in outcome.values() else ("empty" if EMPTY in outcome.values() else ERROR)
        session.merge(state)
        session.commit()
        attempt = state.attempts
        trigger = state.trigger

    if counted:
        if event == "healed":
            summary.healed = 1
        else:
            summary.still_flagged = 1
        if event == "gave_up":
            summary.gave_up = 1
    else:
        summary.not_counted = 1
        if event == "healed":
            summary.healed_by_cache = 1  # a partial refetch cleared the flag; the attempt itself is not counted
    summary.guard_hits = 1 if guarded else 0

    line = (
        f"Statement recheck {ticker}: trigger {trigger}, attempt {attempt}"
        f"{'' if counted else ' (not counted: ' + ', '.join(f'{k} {v}' for k, v in outcome.items() if v not in (OK, GUARD)) + ')'}, "
        f"rules {','.join(before_rules) or '-'} -> {','.join(after_ev.rules) or '-'}, "
        f"filingDate {_newest_filing_dates(before)} -> {_newest_filing_dates(after)}, result {state.last_result}"
    )
    logger.info(line)

    if any(o == OK for o in outcome.values()) and rescore is not None:
        try:
            await rescore(ticker, cache_only=True)  # zero FMP calls; refreshes the Screener row from the rows just written
        except Exception as exc:  # noqa: BLE001 -- the nightly 3:25 recompute covers it
            logger.warning("Statement recheck %s: score refresh failed: %s", ticker, exc)
    return summary, line


def _merge(total: RecheckSummary, part: RecheckSummary) -> None:
    for name in ("healed", "healed_by_cache", "still_flagged", "gave_up", "guard_hits", "not_counted", "errors", "calls"):
        setattr(total, name, getattr(total, name) + getattr(part, name))


async def run_statement_recheck(
    engine: Engine,
    tickers: list[str],
    today: date | None = None,
    now: datetime | None = None,
    rescore: Callable[..., Awaitable] | None = None,
    max_calls: int = RECHECK_MAX_CALLS_PER_NIGHT,
) -> RecheckSummary:
    """Scan `tickers` (cache only), then recheck the due ones within the nightly call cap. Never raises for one
    ticker's failure; the caller wraps the whole call as well."""
    now = now or datetime.now()
    today = today or now.date()
    total = RecheckSummary()

    with Session(engine) as session:
        for result in sr.scan_tickers(session, tickers, today, now):
            if result.evaluation.flagged:
                total.scanned_flagged += 1
            if result.event == "healed":
                total.healed_by_cache += 1
            elif result.event == "gave_up" or (result.event in ("new", "rearmed") and result.state and result.state.status == sr.GAVE_UP):
                total.gave_up += 1
        due = [s.ticker for s in due_states(session, tickers, today)]

    max_tickers = max_calls // RECHECK_CALLS_PER_TICKER
    for index, ticker in enumerate(due):
        # Cap in calls actually made: a ticker whose calls were all blocked made none and costs no slot.
        if total.calls + RECHECK_CALLS_PER_TICKER > max_calls:
            total.deferred = len(due) - index
            logger.info(
                "Statement recheck: call cap (%d calls, %d tickers) reached; %d due ticker(s) deferred to a later night: %s",
                max_calls,
                max_tickers,
                total.deferred,
                ", ".join(due[index:]),
            )
            break
        try:
            part, _line = await recheck_ticker(engine, ticker, today, now, rescore)
        except Exception as exc:  # noqa: BLE001 -- one ticker must never stop the rest of the recheck
            logger.error("Statement recheck %s: FAILED - %s", ticker, exc)
            total.errors += 1
            continue
        total.selected += 1
        _merge(total, part)
    return total
