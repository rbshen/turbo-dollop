"""Recheck of flagged statements: detection and state machine (docs/specs/statement-data-quality.md,
"Recheck of flagged statements").

A cached statement row counts as fresh until the next reported earnings date + 2 days
(core/cache.py::get_or_fetch_earnings_aware), whatever its content, so a bad newest quarter can sit frozen
for 10-73 days. This module finds the tickers whose newest cached quarterly rows trip one of the existing
read-time rules, or whose newest quarter never landed at FMP, and keeps one `RecheckState` row per ticker
that drives a bounded nightly refetch (pipeline/nightly_fundamentals_fetch.py).

The rules themselves are NOT re-implemented here: the placeholder cash-flow test, the scale-break check and
the newest-quarter completeness gate are the helpers the scoring path already uses. Only `not_landed` is new.

`evaluate_rules` and the transition/cadence functions are pure; `load_cached_statements` and `scan_tickers`
are the only I/O (cache reads, `RecheckState` writes), and neither touches the network."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import NamedTuple

from sqlmodel import Session, select

from core.models import FundamentalsCache, RecheckState
from helpers.balance_sheet_gate import (
    ALIGN_TOLERANCE_DAYS,
    DEBT_BASIS_SHORT_PLUS_LONG,
    DEBT_BASIS_TOTAL_DEBT,
    select_complete_balance_sheet,
)
from helpers.earnings import most_recent_reported_earnings_date
from helpers.ttm import is_placeholder_cash_flow_row, is_scale_broken_row
from scoring.classification import classify_company_type

logger = logging.getLogger(__name__)

# Triggers, in priority order: the first one tripped is the row's `trigger`; every one tripped is in `rules_tripped`.
PLACEHOLDER_CF = "placeholder_cf"
DEBT_REMAP = "debt_remap"
CURRENT_ASSETS_REMAP = "current_assets_remap"
SCALE_BREAK = "scale_break"
NOT_LANDED = "not_landed"

ACTIVE, HEALED, GAVE_UP, CHRONIC = "active", "healed", "gave_up", "chronic"

# not_landed: the last reported earnings date must be MORE than this many days old before a missing quarter counts
# (FMP's own lag after an earnings date; core/cache.py's EARNINGS_STALENESS_BUFFER_DAYS is 2).
NOT_LANDED_MIN_DAYS_SINCE_EARNINGS = 3
# not_landed, test A: the newest cached quarterly income period ends MORE than this many days before the last reported
# earnings date. A landed quarter ends ~20-75 days before its earnings date, a not-landed one ~110-165 (the prior
# quarter), so 100 sits between the two populations.
NOT_LANDED_PERIOD_GAP_DAYS = 100
# not_landed, test B reuses balance_sheet_gate.ALIGN_TOLERANCE_DAYS (10) as the allowed spread between statements.

# Recheck window: stop this many days after the anchor date.
WINDOW_DAYS = 60
# Cadence: every night for the first DAILY_ATTEMPTS counted attempts, then at least this many days apart.
DAILY_ATTEMPTS = 7
THIRD_NIGHT_DAYS = 3
# Chronic: more than half of the last four quarterly cash-flow rows are placeholders; recheck at most this often.
CHRONIC_WINDOW_QUARTERS = 4
CHRONIC_MIN_PLACEHOLDERS = 3
CHRONIC_RECHECK_DAYS = 365


class Statements(NamedTuple):
    """One ticker's cached rows, each list most-recent-first as FMP serves it."""

    income_quarterly: list[dict]
    balance_quarterly: list[dict]
    cash_flow_quarterly: list[dict]
    cash_flow_annual: list[dict]
    earnings: list[dict]


@dataclass(frozen=True)
class Flag:
    rule: str
    anchor: date
    filing_date: str | None  # the flagged row's filingDate as FMP served it (None for a not_landed flag)


@dataclass
class Evaluation:
    flags: list[Flag] = field(default_factory=list)
    chronic: bool = False

    @property
    def flagged(self) -> bool:
        return bool(self.flags)

    @property
    def trigger(self) -> str | None:
        return self.flags[0].rule if self.flags else None

    @property
    def anchor(self) -> date | None:
        return self.flags[0].anchor if self.flags else None

    @property
    def rules(self) -> list[str]:
        return [f.rule for f in self.flags]


def _parse_day(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def row_filing_date(row: dict) -> str | None:
    """The row's filingDate as served, else its acceptedDate day, else None."""
    return (row.get("filingDate") or None) or ((row.get("acceptedDate") or "")[:10] or None)


def _row_anchor(row: dict) -> date | None:
    """filingDate, else acceptedDate, else the period end."""
    return _parse_day(row.get("filingDate")) or _parse_day(row.get("acceptedDate")) or _parse_day(row.get("date"))


def _newest_period_end(rows: list[dict]) -> date | None:
    return _parse_day(rows[0].get("date")) if rows else None


def is_chronic(statements: Statements) -> bool:
    """More than half of the last four quarterly cash-flow rows are placeholders (HSBC: about 11 of 12)."""
    recent = statements.cash_flow_quarterly[:CHRONIC_WINDOW_QUARTERS]
    placeholders = sum(1 for row in recent if is_placeholder_cash_flow_row(row, statements.income_quarterly))
    return placeholders >= CHRONIC_MIN_PLACEHOLDERS


def not_landed_flag(statements: Statements, today: date) -> Flag | None:
    """The newest reported quarter has not reached the cached statements.

    R = last reported earnings date (helpers/earnings.py: a past date with a real actual). Fires when R is more than
    NOT_LANDED_MIN_DAYS_SINCE_EARNINGS days old AND either
      A. the newest cached quarterly income period ends more than NOT_LANDED_PERIOD_GAP_DAYS before R, or
      B. the income statement's newest period ends more than ALIGN_TOLERANCE_DAYS after the balance sheet's or the
         cash-flow statement's newest period (one statement landed, the others did not).
    No cached earnings or no income statement: never fires. Anchor = R."""
    reported = most_recent_reported_earnings_date(statements.earnings)
    income_end = _newest_period_end(statements.income_quarterly)
    if reported is None or income_end is None:
        return None
    if (today - reported).days <= NOT_LANDED_MIN_DAYS_SINCE_EARNINGS:
        return None
    gap_a = (reported - income_end).days > NOT_LANDED_PERIOD_GAP_DAYS
    spread_b = False
    for other in (statements.balance_quarterly, statements.cash_flow_quarterly):
        other_end = _newest_period_end(other)
        if other_end is not None and (income_end - other_end).days > ALIGN_TOLERANCE_DAYS:
            spread_b = True
    if not (gap_a or spread_b):
        return None
    return Flag(NOT_LANDED, reported, None)


def evaluate_rules(statements: Statements, company_type: str | None, today: date) -> Evaluation:
    """Every rule the newest cached rows trip, in trigger priority order. Reuses the existing helpers as they are:
    helpers/ttm.py::is_placeholder_cash_flow_row / is_scale_broken_row and
    helpers/balance_sheet_gate.py::select_complete_balance_sheet (the debt basis and the current-assets check chosen
    the way get_step5_data chooses them from `company_type`)."""
    flags: list[Flag] = []
    cash_flow_q, cash_flow_a = statements.cash_flow_quarterly, statements.cash_flow_annual

    if cash_flow_q and is_placeholder_cash_flow_row(cash_flow_q[0], statements.income_quarterly):
        flags.append(Flag(PLACEHOLDER_CF, _row_anchor(cash_flow_q[0]) or today, row_filing_date(cash_flow_q[0])))

    if statements.balance_quarterly:
        is_reit = company_type == "REIT/Property Developer"
        selection = select_complete_balance_sheet(
            statements.balance_quarterly,
            DEBT_BASIS_TOTAL_DEBT if is_reit else DEBT_BASIS_SHORT_PLUS_LONG,
            check_current_assets=not is_reit,
        )
        if selection.fallback_used:
            newest = statements.balance_quarterly[0]
            flags.append(Flag(selection.reason, _row_anchor(newest) or today, row_filing_date(newest)))

    for rows in (cash_flow_q, cash_flow_a):
        if rows and is_scale_broken_row(rows, 0):
            flags.append(Flag(SCALE_BREAK, _row_anchor(rows[0]) or today, row_filing_date(rows[0])))
            break

    landed = not_landed_flag(statements, today)
    if landed is not None:
        flags.append(landed)

    # Stable priority order = the constant order above.
    order = [PLACEHOLDER_CF, DEBT_REMAP, CURRENT_ASSETS_REMAP, SCALE_BREAK, NOT_LANDED]
    flags.sort(key=lambda f: order.index(f.rule))
    return Evaluation(flags=flags, chronic=bool(flags) and is_chronic(statements))


def window_end(anchor: date) -> date:
    return anchor + timedelta(days=WINDOW_DAYS)


def window_days_remaining(state: RecheckState, today: date) -> int:
    return (window_end(state.anchor_date) - today).days


def _new_episode(ticker: str, ev: Evaluation, today: date, now: datetime, episodes: int) -> RecheckState:
    anchor = ev.anchor
    if ev.chronic:
        status, last_result = CHRONIC, None
    elif today > window_end(anchor):
        # Seeded already past the window: recorded, never retried.
        status, last_result = GAVE_UP, "seeded_expired"
    else:
        status, last_result = ACTIVE, None
    return RecheckState(
        ticker=ticker,
        trigger=ev.trigger,
        anchor_date=anchor,
        first_flagged_at=now,
        attempts=0,
        last_attempt_at=None,
        last_result=last_result,
        status=status,
        rules_tripped=",".join(ev.rules),
        episodes=episodes,
    )


def apply_evaluation(
    state: RecheckState | None, ticker: str, ev: Evaluation, today: date, now: datetime
) -> tuple[RecheckState | None, str]:
    """The state after one evaluation of the cached rows, and what happened: one of
    "none" | "new" | "rearmed" | "healed" | "gave_up" | "chronic" | "unchanged".

    * No flag: nothing -> nothing; active/gave_up/chronic -> healed (healed_at, days_to_heal_from_anchor); healed stays.
    * Flag, no state -> a new episode (active, chronic, or gave_up when already past the window).
    * Flag, healed state -> a new episode on the same row (episodes + 1).
    * Flag, existing state -> kept: the anchor never moves within an episode, so a filingDate that moved but is still
      flagged cannot extend the window; only an anchor more than WINDOW_DAYS later than the stored one is a new episode.
      Active past the window -> gave_up; chronic detected -> chronic; chronic no longer detected -> active/gave_up."""
    if not ev.flagged:
        if state is None or state.status == HEALED:
            return state, "none" if state is None else "unchanged"
        state.status = HEALED
        state.healed_at = now
        state.days_to_heal_from_anchor = (today - state.anchor_date).days
        state.last_result = "healed"
        state.rules_tripped = ""
        return state, "healed"

    if state is None:
        fresh = _new_episode(ticker, ev, today, now, episodes=1)
        return fresh, "new"
    if state.status == HEALED or ev.anchor > state.anchor_date + timedelta(days=WINDOW_DAYS):
        return _new_episode(ticker, ev, today, now, episodes=state.episodes + 1), "rearmed"

    state.rules_tripped = ",".join(ev.rules)
    if ev.chronic:
        changed = state.status != CHRONIC
        state.status = CHRONIC
        return state, "chronic" if changed else "unchanged"
    if state.status == CHRONIC:
        state.status = ACTIVE  # no longer chronic: the window rule applies again (falls through below)
    if state.status == ACTIVE and today > window_end(state.anchor_date):
        state.status = GAVE_UP
        return state, "gave_up"
    return state, "unchanged"


def is_due(state: RecheckState, today: date, fetched_today: bool = False) -> bool:
    """Whether tonight's job may spend a recheck on this row.

    `fetched_today`: the normal pass already refetched one of the three quarterly rows tonight, so a first recheck
    would only re-read what it just got (and burn one of the daily attempts): it waits for tomorrow. It only matters
    while the row has never been rechecked; a ticker seeded from a cache fetched on an earlier day is due tonight.
    active: not past the window; every night while fewer than DAILY_ATTEMPTS counted attempts, then at least
    THIRD_NIGHT_DAYS after the last one. chronic: never attempted, or the last attempt at least CHRONIC_RECHECK_DAYS
    ago. healed / gave_up: never."""
    last = state.last_attempt_at.date() if state.last_attempt_at else None
    if state.status == CHRONIC:
        return (not fetched_today) if last is None else (today - last).days >= CHRONIC_RECHECK_DAYS
    if state.status != ACTIVE or today > window_end(state.anchor_date):
        return False
    if last is None:
        return not fetched_today
    if state.attempts < DAILY_ATTEMPTS:
        return last < today
    return (today - last).days >= THIRD_NIGHT_DAYS


def statements_fetched_on(session: Session, ticker: str, day: date) -> bool:
    """True when any of the ticker's three quarterly statement rows was fetched on `day` (the normal pass just ran)."""
    stamps = session.exec(
        select(FundamentalsCache.fetched_at).where(
            FundamentalsCache.ticker == ticker,
            FundamentalsCache.period == "quarterly",
            FundamentalsCache.statement_type.in_(QUARTERLY_STATEMENT_TYPES),
        )
    ).all()
    return any(stamp.date() == day for stamp in stamps)


# --- I/O: cache reads and RecheckState writes (no network) -------------------------------------------------------

QUARTERLY_STATEMENT_TYPES = ("income_statement", "balance_sheet_statement", "cash_flow_statement")

_STATEMENT_KEYS = {
    ("income_statement", "quarterly"): "income_quarterly",
    ("balance_sheet_statement", "quarterly"): "balance_quarterly",
    ("cash_flow_statement", "quarterly"): "cash_flow_quarterly",
    ("cash_flow_statement", "annual"): "cash_flow_annual",
    ("earnings", "latest"): "earnings",
}


def _loads_list(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def load_cached_statements(session: Session, ticker: str) -> tuple[Statements, str | None]:
    """The ticker's cached rows (never fetches) and its company type, from the cached profile."""
    rows = session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker,
            FundamentalsCache.statement_type.in_(["income_statement", "balance_sheet_statement", "cash_flow_statement", "earnings", "profile"]),
        )
    ).all()
    lists: dict[str, list[dict]] = {name: [] for name in _STATEMENT_KEYS.values()}
    profile: dict = {}
    for row in rows:
        name = _STATEMENT_KEYS.get((row.statement_type, row.period))
        if name is not None:
            lists[name] = _loads_list(row.raw_json)
        elif row.statement_type == "profile":
            parsed = _loads_list(row.raw_json)
            profile = parsed[0] if parsed else {}
    company_type = classify_company_type(
        profile.get("sector"), profile.get("industry"), ticker, is_fund=bool(profile.get("isEtf") or profile.get("isFund"))
    )
    return Statements(**lists), company_type


class ScanResult(NamedTuple):
    ticker: str
    evaluation: Evaluation
    event: str
    state: RecheckState | None


def scan_tickers(
    session: Session, tickers: list[str], today: date | None = None, now: datetime | None = None, persist: bool = True
) -> list[ScanResult]:
    """Evaluate the cached rows of every ticker and move its RecheckState (apply_evaluation). Reads the cache only.
    `persist=False` computes the same transitions on a detached copy and writes nothing (the read-only dry run)."""
    now = now or datetime.now()
    today = today or now.date()
    results: list[ScanResult] = []
    for ticker in tickers:
        statements, company_type = load_cached_statements(session, ticker)
        ev = evaluate_rules(statements, company_type, today)
        existing = session.get(RecheckState, ticker)
        if existing is not None and not persist:
            session.expunge(existing)  # transitions below must not reach the database
        state, event = apply_evaluation(existing, ticker, ev, today, now)
        if state is not None and persist:
            session.merge(state)
        if event not in ("none", "unchanged"):
            logger.info("Statement recheck scan %s: %s (rules: %s)", ticker, event, ",".join(ev.rules) or "-")
        results.append(ScanResult(ticker, ev, event, state))
    if persist:
        session.commit()
    return results
