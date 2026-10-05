"""data/statement_recheck_data.py and its wiring in pipeline/nightly_fundamentals_fetch.py: the nightly recheck of
flagged statements. FMP is mocked; every test builds its own in-memory engine and hands it to the code under test
(the CLAUDE.md rule for anything that touches the cache)."""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import core.cache as cache_module
import core.data_groups as data_groups
import data.statement_recheck_data as recheck
import pipeline.nightly_fundamentals_fetch as nightly
from clients.fmp_client import FMPVariantUnavailableError
from core.models import FundamentalsCache, RecheckState
from helpers import statement_recheck as sr
from test_statement_recheck import QUARTER_ENDS, balance, cash_flow, earnings, healthy, income

TODAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 2, 30)
CACHED_AT = datetime(2026, 9, 20, 3, 0)

BAD_BALANCE = [balance("2026-06-30", long=300)] + [balance(d) for d in QUARTER_ENDS[1:]]  # debt remap
GOOD_BALANCE = [balance("2026-06-30", long=1000, filing="2026-09-12")] + [balance(d) for d in QUARTER_ENDS[1:]]


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def seed(engine, ticker, statements=None, *, state=True, first_flagged_days_ago=2, anchor_days_ago=20, **state_kwargs):
    """Cache rows for `ticker` (all stamped CACHED_AT) plus, by default, an active RecheckState for it."""
    statements = statements or healthy(balance_quarterly=BAD_BALANCE)
    rows = {
        ("income_statement", "quarterly"): statements.income_quarterly,
        ("balance_sheet_statement", "quarterly"): statements.balance_quarterly,
        ("cash_flow_statement", "quarterly"): statements.cash_flow_quarterly,
        ("cash_flow_statement", "annual"): statements.cash_flow_annual,
        ("earnings", "latest"): statements.earnings,
        ("profile", "latest"): [{"sector": "Technology", "industry": "Software"}],
    }
    with Session(engine) as session:
        for (statement_type, period), payload in rows.items():
            session.add(
                FundamentalsCache(ticker=ticker, statement_type=statement_type, period=period, fetched_at=CACHED_AT, raw_json=json.dumps(payload))
            )
        if state:
            fields = dict(
                ticker=ticker,
                trigger=sr.DEBT_REMAP,
                anchor_date=TODAY - timedelta(days=anchor_days_ago),
                first_flagged_at=datetime.combine(TODAY - timedelta(days=first_flagged_days_ago), datetime.min.time()),
                status=sr.ACTIVE,
            )
            fields.update(state_kwargs)
            session.add(RecheckState(**fields))
        session.commit()


def cache_row(engine, ticker, statement_type, period="quarterly"):
    with Session(engine) as session:
        row = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == ticker, FundamentalsCache.statement_type == statement_type, FundamentalsCache.period == period
            )
        ).one()
        return row.raw_json, row.fetched_at


def state_of(engine, ticker) -> RecheckState:
    with Session(engine) as session:
        return session.get(RecheckState, ticker)


class FakeFMP:
    """Stands in for the three statement endpoints. `answers[(kind)]` is a list payload, an Exception to raise, or a
    callable taking the ticker; calls are recorded."""

    def __init__(self, monkeypatch, income_rows=None, balance_rows=None, cash_flow_rows=None):
        self.calls: list[tuple[str, str]] = []
        self.answers = {
            "income": income_rows if income_rows is not None else healthy().income_quarterly,
            "balance": balance_rows if balance_rows is not None else GOOD_BALANCE,
            "cash flow": cash_flow_rows if cash_flow_rows is not None else healthy().cash_flow_quarterly,
        }
        monkeypatch.setattr(recheck.fmp_client, "get_income_statement", self._make("income"))
        monkeypatch.setattr(recheck.fmp_client, "get_balance_sheet_statement", self._make("balance"))
        monkeypatch.setattr(recheck.fmp_client, "get_cash_flow_statement", self._make("cash flow"))

    def _make(self, kind):
        async def call(ticker, period, limit):
            self.calls.append((ticker, kind))
            answer = self.answers[kind]
            if isinstance(answer, dict) and ticker in answer:
                answer = answer[ticker]
            if isinstance(answer, Exception):
                raise answer
            return answer

        return call


def run(engine, tickers, rescore=None, **kwargs):
    return asyncio.run(recheck.run_statement_recheck(engine, tickers, today=TODAY, now=NOW, rescore=rescore, **kwargs))


def variant_error():
    return FMPVariantUnavailableError("variant refused", "fundamentals", "/balance-sheet-statement?limit=12&period=quarter", "quarterly balance sheet")


def status_error(code):
    request = httpx.Request("GET", "https://fmp.test/x")
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=httpx.Response(code, request=request))


@pytest.fixture()
def engine(monkeypatch):
    # `core.cache` and `helpers`/`data` take the session explicitly: nothing here reads the real engine.
    return make_engine()


# ---- heal / still flagged ------------------------------------------------------------------------


def test_a_healed_refetch_writes_the_new_rows_marks_the_state_healed_and_rescores(engine, monkeypatch):
    seed(engine, "ZTS")
    fmp = FakeFMP(monkeypatch)
    rescored = []

    async def rescore(ticker, cache_only=False):
        rescored.append((ticker, cache_only))

    summary = run(engine, ["ZTS"], rescore=rescore)

    assert fmp.calls == [("ZTS", "income"), ("ZTS", "balance"), ("ZTS", "cash flow")]
    assert (summary.selected, summary.healed, summary.still_flagged, summary.calls) == (1, 1, 0, 3)
    state = state_of(engine, "ZTS")
    assert (state.status, state.attempts, state.last_result, state.days_to_heal_from_anchor) == (sr.HEALED, 1, "healed", 20)
    assert state.healed_at == NOW and state.last_attempt_at == NOW
    raw, fetched_at = cache_row(engine, "ZTS", "balance_sheet_statement")
    assert json.loads(raw)[0]["filingDate"] == "2026-09-12" and fetched_at > CACHED_AT
    assert rescored == [("ZTS", True)]


def test_only_the_three_quarterly_statement_rows_are_touched(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch)
    before = {key: cache_row(engine, "ZTS", *key) for key in [("cash_flow_statement", "annual"), ("earnings", "latest"), ("profile", "latest")]}

    run(engine, ["ZTS"])

    assert {key: cache_row(engine, "ZTS", *key) for key in before} == before


def test_a_refetch_that_still_finds_the_bad_row_counts_the_attempt_keeps_the_state_and_never_loops(engine, monkeypatch):
    seed(engine, "ZTS")
    fmp = FakeFMP(monkeypatch, balance_rows=BAD_BALANCE)

    summary = run(engine, ["ZTS"])

    assert (summary.selected, summary.still_flagged, summary.healed) == (1, 1, 0)
    state = state_of(engine, "ZTS")
    assert (state.status, state.attempts, state.last_result) == (sr.ACTIVE, 1, "still_flagged")
    assert len(fmp.calls) == 3  # one pass of three calls, no retry loop
    # Same night again: already attempted today, not due.
    assert run(engine, ["ZTS"]).selected == 0
    assert len(fmp.calls) == 3


def test_attempt_numbers_accumulate_across_nights(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, balance_rows=BAD_BALANCE)

    for night in range(3):
        asyncio.run(recheck.run_statement_recheck(engine, ["ZTS"], today=TODAY + timedelta(days=night), now=NOW + timedelta(days=night)))

    assert state_of(engine, "ZTS").attempts == 3


def test_the_log_line_carries_trigger_attempt_rules_and_filing_dates(engine, monkeypatch, caplog):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch)

    with caplog.at_level(logging.INFO, logger="data.statement_recheck_data"):
        run(engine, ["ZTS"])

    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Statement recheck ZTS: trigger"))
    assert "trigger debt_remap" in line and "attempt 1" in line
    assert "rules debt_remap -> -" in line
    assert "balance 2026-08-07" in line and "balance 2026-09-12" in line  # filingDate before -> after


# ---- never counted: blocked / failed / empty ----------------------------------------------------


def test_a_failed_fetch_never_wipes_or_restamps_the_row_and_is_not_an_attempt(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, balance_rows=httpx.ReadTimeout("slow"))
    before = cache_row(engine, "ZTS", "balance_sheet_statement")

    summary = run(engine, ["ZTS"])

    assert cache_row(engine, "ZTS", "balance_sheet_statement") == before  # byte-identical raw_json and fetched_at
    state = state_of(engine, "ZTS")
    assert (state.attempts, state.last_attempt_at, state.last_result, state.status) == (0, None, "error", sr.ACTIVE)
    assert (summary.selected, summary.not_counted, summary.still_flagged) == (1, 1, 0)


@pytest.mark.parametrize("answer", [[], {}, {"Error Message": "nope"}, None])
def test_an_empty_or_non_list_answer_is_not_written_and_is_not_an_attempt(engine, monkeypatch, answer):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, balance_rows=answer if answer is not None else [])
    before = cache_row(engine, "ZTS", "balance_sheet_statement")

    run(engine, ["ZTS"])

    assert cache_row(engine, "ZTS", "balance_sheet_statement") == before
    assert (state_of(engine, "ZTS").attempts, state_of(engine, "ZTS").last_result) == (0, "empty")


def test_a_402_is_not_an_attempt_and_writes_nothing(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, balance_rows=status_error(402))
    before = cache_row(engine, "ZTS", "balance_sheet_statement")

    run(engine, ["ZTS"])

    assert cache_row(engine, "ZTS", "balance_sheet_statement") == before
    assert (state_of(engine, "ZTS").attempts, state_of(engine, "ZTS").last_result) == (0, "blocked")


def test_a_500_or_429_is_an_error_not_a_block(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, balance_rows=status_error(429))

    run(engine, ["ZTS"])

    assert state_of(engine, "ZTS").last_result == "error"


def test_a_restricted_request_variant_is_not_an_attempt(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, balance_rows=variant_error())
    before = cache_row(engine, "ZTS", "balance_sheet_statement")

    summary = run(engine, ["ZTS"])

    assert cache_row(engine, "ZTS", "balance_sheet_statement") == before
    assert state_of(engine, "ZTS").attempts == 0 and state_of(engine, "ZTS").last_result == "blocked"
    assert summary.calls == 2  # the variant refusal made no network call


def test_a_disabled_fundamentals_group_makes_no_call_and_is_not_an_attempt(engine, monkeypatch):
    seed(engine, "ZTS")
    fmp = FakeFMP(monkeypatch)
    data_groups.set_group_enabled("fundamentals", False)
    before = {t: cache_row(engine, "ZTS", t) for t in ("income_statement", "balance_sheet_statement", "cash_flow_statement")}

    summary = run(engine, ["ZTS"])

    assert fmp.calls == [] and summary.calls == 0
    assert {t: cache_row(engine, "ZTS", t) for t in before} == before
    state = state_of(engine, "ZTS")
    assert (state.attempts, state.last_result) == (0, "blocked")


def test_the_master_switch_off_makes_no_call_and_is_not_an_attempt(engine, monkeypatch):
    seed(engine, "ZTS")
    fmp = FakeFMP(monkeypatch)
    data_groups.set_master(False)

    run(engine, ["ZTS"])

    assert fmp.calls == [] and state_of(engine, "ZTS").attempts == 0


def test_a_partial_failure_keeps_what_succeeded_and_counts_no_attempt(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, cash_flow_rows=httpx.ConnectError("down"))

    summary = run(engine, ["ZTS"])

    raw, _ = cache_row(engine, "ZTS", "balance_sheet_statement")
    assert json.loads(raw)[0]["filingDate"] == "2026-09-12"  # income + balance were written (production semantics)
    state = state_of(engine, "ZTS")
    # The written balance sheet cleared the flag, so the row heals from the cache; the failed call is no attempt.
    assert (state.status, state.attempts, state.last_attempt_at) == (sr.HEALED, 0, None)
    assert (summary.healed, summary.healed_by_cache, summary.not_counted) == (0, 1, 1)


def test_a_partial_failure_on_a_still_flagged_ticker_is_an_error_not_an_attempt(engine, monkeypatch):
    seed(engine, "ZTS")
    FakeFMP(monkeypatch, balance_rows=BAD_BALANCE, cash_flow_rows=httpx.ConnectError("down"))

    run(engine, ["ZTS"])

    state = state_of(engine, "ZTS")
    assert (state.status, state.attempts, state.last_result) == (sr.ACTIVE, 0, "error")


# ---- regression guard ----------------------------------------------------------------------------


def test_the_regression_guard_does_not_write_a_live_balance_sheet_that_trips_a_rule_the_cached_one_does_not(engine, monkeypatch):
    # The flag is a placeholder cash-flow row; the cached balance sheet is clean, the live one is a debt remap.
    cf = [cash_flow("2026-06-30", placeholder=True)] + [cash_flow(d) for d in QUARTER_ENDS[1:]]
    seed(engine, "AZO", healthy(cash_flow_quarterly=cf), trigger=sr.PLACEHOLDER_CF)
    FakeFMP(monkeypatch, balance_rows=BAD_BALANCE, cash_flow_rows=cf)
    before = cache_row(engine, "AZO", "balance_sheet_statement")

    summary = run(engine, ["AZO"])

    assert cache_row(engine, "AZO", "balance_sheet_statement") == before
    assert summary.guard_hits == 1
    state = state_of(engine, "AZO")
    assert (state.attempts, state.last_result, state.status) == (1, "regression_guard", sr.ACTIVE)  # the guard still counts as an attempt


def test_the_regression_guard_covers_a_live_cash_flow_placeholder_using_the_live_income(engine, monkeypatch):
    seed(engine, "ZTS")  # flagged: cached debt remap; cached cash flow is clean
    placeholder = [cash_flow("2026-06-30", placeholder=True)] + [cash_flow(d) for d in QUARTER_ENDS[1:]]
    FakeFMP(monkeypatch, cash_flow_rows=placeholder)
    before = cache_row(engine, "ZTS", "cash_flow_statement")

    summary = run(engine, ["ZTS"])

    assert cache_row(engine, "ZTS", "cash_flow_statement") == before
    assert summary.guard_hits == 1
    assert json.loads(cache_row(engine, "ZTS", "balance_sheet_statement")[0])[0]["filingDate"] == "2026-09-12"  # healed balance sheet is kept


def test_a_live_row_that_trips_the_same_rule_as_the_cached_one_is_written_not_vetoed(engine, monkeypatch):
    seed(engine, "ZTS")
    newer_bad = [balance("2026-06-30", long=300, filing="2026-09-12")] + [balance(d) for d in QUARTER_ENDS[1:]]
    FakeFMP(monkeypatch, balance_rows=newer_bad)

    summary = run(engine, ["ZTS"])

    assert summary.guard_hits == 0
    assert json.loads(cache_row(engine, "ZTS", "balance_sheet_statement")[0])[0]["filingDate"] == "2026-09-12"


# ---- selection: cadence, cap, ordering ------------------------------------------------------------


def test_only_due_active_and_chronic_rows_of_the_run_are_rechecked(engine, monkeypatch):
    seed(engine, "DUE")
    seed(engine, "TODAY", first_flagged_days_ago=0, last_attempt_at=NOW, attempts=1)  # attempted tonight already
    seed(engine, "DONE", healthy(), status=sr.HEALED)  # clean cache: stays healed
    seed(engine, "GAVE", status=sr.GAVE_UP, anchor_days_ago=90)  # same bad row, long past the window: stays gave_up
    seed(engine, "OTHER")  # a due row, but not in this run's ticker list
    fmp = FakeFMP(monkeypatch)

    summary = run(engine, ["DUE", "TODAY", "DONE", "GAVE"])

    assert {t for t, _ in fmp.calls} == {"DUE"} and summary.selected == 1


def test_a_ticker_the_normal_pass_just_refetched_waits_for_tomorrow(engine, monkeypatch):
    seed(engine, "ZTS", first_flagged_days_ago=0)
    with Session(engine) as session:
        for row in session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "balance_sheet_statement")).all():
            row.fetched_at = NOW
            session.add(row)
        session.commit()
    fmp = FakeFMP(monkeypatch)

    assert run(engine, ["ZTS"]).selected == 0 and fmp.calls == []


def test_the_nightly_cap_is_60_calls_20_tickers_oldest_attempt_first_and_defers_the_rest(engine, monkeypatch, caplog):
    tickers = [f"T{i:02d}" for i in range(25)]
    for i, ticker in enumerate(tickers):
        # T00 never attempted ... the rest attempted on progressively more recent nights; T24 the most recent.
        seed(engine, ticker, attempts=1 if i else 0, last_attempt_at=None if i == 0 else NOW - timedelta(days=30 - i))
    fmp = FakeFMP(monkeypatch, balance_rows=BAD_BALANCE)

    with caplog.at_level(logging.INFO, logger="data.statement_recheck_data"):
        summary = run(engine, tickers)

    assert (summary.selected, summary.deferred, summary.calls) == (20, 5, 60)
    done = [t for t, kind in fmp.calls if kind == "income"]
    assert done == tickers[:20]  # oldest attempt first, the 5 most recently attempted wait
    assert any("deferred" in r.getMessage() and "T20" in r.getMessage() for r in caplog.records)
    # The deferred tickers were not touched.
    assert state_of(engine, "T24").attempts == 1


def test_blocked_tickers_make_no_calls_and_do_not_eat_the_cap(engine, monkeypatch):
    tickers = [f"B{i:02d}" for i in range(25)]
    for ticker in tickers:
        seed(engine, ticker)
    FakeFMP(monkeypatch, balance_rows=variant_error(), income_rows=variant_error(), cash_flow_rows=variant_error())

    summary = run(engine, tickers)

    assert (summary.selected, summary.deferred, summary.calls) == (25, 0, 0)


def test_a_flag_already_past_the_window_is_recorded_as_gave_up_and_costs_no_call(engine, monkeypatch):
    old = [balance("2026-06-30", long=300, filing="2026-06-01")] + [balance(d) for d in QUARTER_ENDS[1:]]
    seed(engine, "OLD", healthy(balance_quarterly=old), state=False)
    fmp = FakeFMP(monkeypatch)

    summary = run(engine, ["OLD"])

    assert fmp.calls == [] and summary.gave_up == 1 and summary.selected == 0
    assert (state_of(engine, "OLD").status, state_of(engine, "OLD").last_result) == (sr.GAVE_UP, "seeded_expired")


def test_a_ticker_flagged_for_the_first_time_is_seeded_and_rechecked_the_same_night_when_its_cache_is_old(engine, monkeypatch):
    seed(engine, "ZTS", state=False)
    fmp = FakeFMP(monkeypatch)

    summary = run(engine, ["ZTS"])

    assert len(fmp.calls) == 3 and summary.healed == 1
    assert state_of(engine, "ZTS").status == sr.HEALED


def test_chronic_rows_are_rechecked_once_a_year_at_most(engine, monkeypatch):
    chronic_cf = [cash_flow(d, placeholder=True) for d in QUARTER_ENDS]  # every quarter a placeholder
    seed(engine, "HSBC", healthy(cash_flow_quarterly=chronic_cf), trigger=sr.PLACEHOLDER_CF, status=sr.CHRONIC, attempts=1, last_attempt_at=NOW - timedelta(days=200), first_flagged_days_ago=250)
    fmp = FakeFMP(monkeypatch)

    assert run(engine, ["HSBC"]).selected == 0 and fmp.calls == []

    with Session(engine) as session:
        state = session.get(RecheckState, "HSBC")
        state.last_attempt_at = NOW - timedelta(days=365)
        session.add(state)
        session.commit()
    assert run(engine, ["HSBC"]).selected == 1


# ---- the earnings-aware path is not extended or reset ------------------------------------------------


def test_a_recheck_stamp_does_not_make_a_row_look_fresh_across_a_later_earnings_cutoff(engine, monkeypatch):
    seed(engine, "ZTS", healthy(balance_quarterly=BAD_BALANCE, earnings=earnings("2026-10-04")))
    FakeFMP(monkeypatch, balance_rows=BAD_BALANCE)
    run(engine, ["ZTS"])  # stamps the three quarterly rows with NOW (2026-10-05)
    with Session(engine) as session:
        row = session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "balance_sheet_statement")).one()
    assert row.fetched_at > CACHED_AT

    class LaterDate(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 7)

    monkeypatch.setattr(cache_module, "date", LaterDate)
    # Earnings 2026-10-04 -> cutoff 2026-10-06. Fetched 10-05 (before it): stale once 10-06 is reached, exactly as if
    # the normal pass had made that fetch. The recheck did not mark it fresh through the new earnings date.
    assert cache_module._is_earnings_aware_stale(row, date(2026, 10, 4), 7) is True


# ---- nightly wiring ------------------------------------------------------------------------------------


def _patch_main(monkeypatch, tmp_path, engine):
    monkeypatch.setattr(nightly, "engine", engine)
    monkeypatch.setattr(nightly, "LOG_PATH", tmp_path / "nightly.log")
    monkeypatch.setattr(nightly.fmp_client, "request_count", 0)
    monkeypatch.setattr(nightly.fmp_client, "min_request_interval", 0.0)

    async def noop(ticker, **kwargs):
        return None

    for name in ("get_step1_data", "get_step2_data", "get_step4_data", "get_step5_data", "get_segmentation_data", "get_summary", "compute_ticker_score"):
        monkeypatch.setattr(nightly, name, noop)


def test_main_runs_the_recheck_after_the_normal_pass_and_reports_it(engine, monkeypatch, tmp_path):
    _patch_main(monkeypatch, tmp_path, engine)
    seed(engine, "ZTS", anchor_days_ago=2, first_flagged_days_ago=1)
    # main() uses today's real date: anchor relative to it.
    with Session(engine) as session:
        state = session.get(RecheckState, "ZTS")
        state.anchor_date = date.today() - timedelta(days=5)
        state.first_flagged_at = datetime.now() - timedelta(days=2)
        session.add(state)
        session.commit()
    FakeFMP(monkeypatch)

    result = asyncio.run(nightly.main(tickers=["ZTS"]))

    assert result["failed"] == 0 and result["recheck"]["selected"] == 1 and result["recheck"]["healed"] == 1
    message = _message(result)
    assert "recheck: 1 selected, 1 healed, 0 still flagged, 0 gave up, 0 deferred" in message


def _message(result):
    class Run:
        message = None

        def skip(self, reason):
            raise AssertionError("not skipped")

    run = Run()
    nightly.record_outcome(result, run)
    return run.message


def test_record_outcome_omits_the_recheck_clause_when_nothing_happened():
    result = {"processed": 3, "failed": 0, "calls_made": 10, "duration_seconds": 60.0, "recheck": {"selected": 0, "healed": 0, "deferred": 0}}

    assert "recheck" not in _message(result)


def test_record_outcome_reports_deferred_and_guard_hits():
    result = {
        "processed": 3, "failed": 0, "calls_made": 10, "duration_seconds": 60.0,
        "recheck": {"selected": 20, "healed": 2, "still_flagged": 18, "gave_up": 1, "deferred": 5, "guard_hits": 1},
    }

    message = _message(result)

    assert "recheck: 20 selected, 2 healed, 18 still flagged, 1 gave up, 5 deferred, 1 guard hit(s)" in message


def test_a_recheck_failure_never_fails_the_nightly_run(engine, monkeypatch, tmp_path):
    _patch_main(monkeypatch, tmp_path, engine)

    async def boom(*args, **kwargs):
        raise RuntimeError("recheck exploded")

    monkeypatch.setattr(nightly, "run_statement_recheck", boom)

    result = asyncio.run(nightly.main(tickers=["AAPL"]))

    assert (result["processed"], result["failed"], result["recheck"]) == (1, 0, {})


def test_the_recheck_does_not_run_when_the_fundamentals_group_is_off(engine, monkeypatch, tmp_path):
    _patch_main(monkeypatch, tmp_path, engine)
    seed(engine, "ZTS")
    fmp = FakeFMP(monkeypatch)
    data_groups.set_group_enabled("fundamentals", False)

    result = asyncio.run(nightly.main(tickers=["ZTS"]))

    assert result.get("skipped") is True and fmp.calls == []
    assert "recheck" not in result
