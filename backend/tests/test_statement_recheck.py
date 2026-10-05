"""helpers/statement_recheck.py: trigger detection (with boundaries), the RecheckState transitions, the cadence."""

import json
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from core.models import FundamentalsCache, RecheckState
from helpers import statement_recheck as sr
from helpers.statement_recheck import (
    ACTIVE,
    CHRONIC,
    GAVE_UP,
    HEALED,
    Evaluation,
    Flag,
    Statements,
    apply_evaluation,
    evaluate_rules,
    is_due,
    not_landed_flag,
    scan_tickers,
)

TODAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 2, 0)


# ---- fixtures ---------------------------------------------------------------


def income(period_end, net_income=100.0):
    return {"date": period_end, "fiscalYear": period_end[:4], "period": "Q", "netIncome": net_income}


def cash_flow(period_end, placeholder=False, filing="2026-08-07"):
    row = {
        "date": period_end,
        "fiscalYear": period_end[:4],
        "period": "Q",
        "filingDate": filing,
        "netCashProvidedByOperatingActivities": 0 if placeholder else 500.0,
        "freeCashFlow": 0 if placeholder else 400.0,
        "capitalExpenditure": 0 if placeholder else -100.0,
        "netCashProvidedByInvestingActivities": 0 if placeholder else -120.0,
        "netCashProvidedByFinancingActivities": 0 if placeholder else -50.0,
    }
    return row


def balance(period_end, short=0, long=1000, total_debt=None, liabilities=10_000, assets=20_000, filing="2026-08-07"):
    return {
        "date": period_end,
        "filingDate": filing,
        "shortTermDebt": short,
        "longTermDebt": long,
        "totalDebt": short + long if total_debt is None else total_debt,
        "totalLiabilities": liabilities,
        "totalAssets": assets,
        "totalCurrentAssets": 5_000,
        "totalCurrentLiabilities": 2_000,
    }


def earnings(*reported_dates):
    return [{"date": d, "epsActual": 1.0, "revenueActual": 10.0} for d in reported_dates]


QUARTER_ENDS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]


def healthy(**overrides) -> Statements:
    base = dict(
        income_quarterly=[income(d) for d in QUARTER_ENDS],
        balance_quarterly=[balance(d) for d in QUARTER_ENDS],
        cash_flow_quarterly=[cash_flow(d) for d in QUARTER_ENDS],
        cash_flow_annual=[],
        earnings=earnings("2026-08-04", "2026-05-05"),
    )
    base.update(overrides)
    return Statements(**base)


def rules_of(statements, company_type=None, today=TODAY):
    return evaluate_rules(statements, company_type, today).rules


# ---- a healthy ticker trips nothing ------------------------------------------------


def test_healthy_ticker_trips_no_rule():
    ev = evaluate_rules(healthy(), None, TODAY)

    assert ev.flags == [] and ev.chronic is False


# ---- placeholder_cf ----------------------------------------------------------------


def test_newest_placeholder_cash_flow_row_triggers_with_its_filing_date_as_anchor():
    cf = [cash_flow("2026-06-30", placeholder=True, filing="2026-08-06")] + [cash_flow(d) for d in QUARTER_ENDS[1:]]

    ev = evaluate_rules(healthy(cash_flow_quarterly=cf), None, TODAY)

    assert ev.trigger == sr.PLACEHOLDER_CF
    assert ev.anchor == date(2026, 8, 6)
    assert ev.flags[0].filing_date == "2026-08-06"
    assert ev.chronic is False


def test_placeholder_only_counts_on_the_newest_row():
    cf = [cash_flow("2026-06-30")] + [cash_flow("2026-03-31", placeholder=True)] + [cash_flow(d) for d in QUARTER_ENDS[2:]]

    assert rules_of(healthy(cash_flow_quarterly=cf)) == []


def test_zero_cash_flow_beside_zero_net_income_is_not_a_placeholder():
    cf = [cash_flow("2026-06-30", placeholder=True)] + [cash_flow(d) for d in QUARTER_ENDS[1:]]
    inc = [income("2026-06-30", net_income=0.0)] + [income(d) for d in QUARTER_ENDS[1:]]

    assert rules_of(healthy(cash_flow_quarterly=cf, income_quarterly=inc)) == []


def test_anchor_falls_back_to_accepted_date_then_period_end():
    row = cash_flow("2026-06-30", placeholder=True)
    del row["filingDate"]
    assert evaluate_rules(healthy(cash_flow_quarterly=[row] + [cash_flow(d) for d in QUARTER_ENDS[1:]]), None, TODAY).anchor == date(2026, 6, 30)
    row["acceptedDate"] = "2026-08-05 16:00:00"
    assert evaluate_rules(healthy(cash_flow_quarterly=[row] + [cash_flow(d) for d in QUARTER_ENDS[1:]]), None, TODAY).anchor == date(2026, 8, 5)


# ---- chronic -----------------------------------------------------------------------


@pytest.mark.parametrize("placeholders,chronic", [(2, False), (3, True), (4, True)])
def test_chronic_means_more_than_half_of_the_last_four_cash_flow_rows_are_placeholders(placeholders, chronic):
    cf = [cash_flow(d, placeholder=i < placeholders) for i, d in enumerate(QUARTER_ENDS)]

    ev = evaluate_rules(healthy(cash_flow_quarterly=cf), None, TODAY)

    assert ev.trigger == sr.PLACEHOLDER_CF
    assert ev.chronic is chronic


# ---- debt_remap / current_assets_remap ---------------------------------------------


def test_debt_remap_on_the_newest_balance_sheet_triggers():
    bs = [balance("2026-06-30", long=300)] + [balance(d) for d in QUARTER_ENDS[1:]]  # -70%, liabilities flat

    ev = evaluate_rules(healthy(balance_quarterly=bs), None, TODAY)

    assert ev.rules == [sr.DEBT_REMAP]
    assert ev.anchor == date(2026, 8, 7)


def test_debt_remap_uses_total_debt_on_the_reit_path_and_short_plus_long_otherwise():
    # shortTermDebt/longTermDebt collapse but FMP's totalDebt does not: only Standard sees a remap.
    bs = [balance("2026-06-30", long=300, total_debt=1000)] + [balance(d) for d in QUARTER_ENDS[1:]]

    assert rules_of(healthy(balance_quarterly=bs), None) == [sr.DEBT_REMAP]
    assert rules_of(healthy(balance_quarterly=bs), "REIT/Property Developer") == []


def test_current_assets_remap_triggers_on_standard_only():
    newest = balance("2026-06-30") | {"totalCurrentAssets": 1_500}  # -70%, everything else flat
    bs = [newest] + [balance(d) for d in QUARTER_ENDS[1:]]

    assert rules_of(healthy(balance_quarterly=bs), None) == [sr.CURRENT_ASSETS_REMAP]
    assert rules_of(healthy(balance_quarterly=bs), "REIT/Property Developer") == []


# ---- scale_break -------------------------------------------------------------------

LINES = [f"line{i}" for i in range(12)]


def scaled_row(period_end, scale=1.0, growth=1.0):
    row = {"date": period_end, "period": "Q", "fiscalYear": period_end[:4], "filingDate": "2026-08-07"}
    for i, key in enumerate(LINES):
        row[key] = (10 ** (6 + i % 6)) * (1 + i / 10) * growth * scale
    return row


def test_scale_broken_newest_quarterly_cash_flow_row_triggers():
    cf = [scaled_row(QUARTER_ENDS[0], scale=1e-6)] + [scaled_row(d, growth=1 + 0.05 * i) for i, d in enumerate(QUARTER_ENDS[1:])]

    assert sr.SCALE_BREAK in rules_of(healthy(cash_flow_quarterly=cf))


def test_scale_broken_newest_annual_cash_flow_row_triggers():
    annual = [scaled_row("2026-06-30", scale=1e-6)] + [scaled_row(f"{y}-06-30", growth=1 + 0.05 * i) for i, y in enumerate(range(2025, 2020, -1))]

    assert rules_of(healthy(cash_flow_annual=annual)) == [sr.SCALE_BREAK]


def test_scale_break_below_the_threshold_does_not_trigger():
    cf = [scaled_row(QUARTER_ENDS[0], scale=1e-2)] + [scaled_row(d, growth=1 + 0.05 * i) for i, d in enumerate(QUARTER_ENDS[1:])]

    assert sr.SCALE_BREAK not in rules_of(healthy(cash_flow_quarterly=cf))


# ---- not_landed (boundaries and the known pre-catch-up cases) ------------------------------------


def landed_check(reported_days_ago, income_end, balance_end=None, cash_end=None):
    reported = TODAY - timedelta(days=reported_days_ago)
    inc, bs, cf = [income(income_end)], [balance(balance_end or income_end)], [cash_flow(cash_end or income_end)]
    statements = Statements(inc, bs, cf, [], earnings(reported.isoformat()))
    return not_landed_flag(statements, TODAY)


def test_not_landed_needs_the_last_earnings_date_to_be_more_than_3_days_old():
    # newest period ends 130 days before the earnings date, so test A holds in every row below.
    for days_ago, fires in [(3, False), (4, True)]:
        reported = TODAY - timedelta(days=days_ago)
        end = (reported - timedelta(days=130)).isoformat()
        assert (landed_check(days_ago, end) is not None) is fires


@pytest.mark.parametrize("gap,fires", [(99, False), (100, False), (101, True)])
def test_not_landed_test_a_gap_boundary_is_strictly_more_than_100_days(gap, fires):
    reported = TODAY - timedelta(days=30)
    end = (reported - timedelta(days=gap)).isoformat()

    assert (landed_check(30, end) is not None) is fires


@pytest.mark.parametrize("spread,fires", [(9, False), (10, False), (11, True)])
def test_not_landed_test_b_income_ahead_of_balance_sheet_or_cash_flow_by_more_than_10_days(spread, fires):
    income_end = date(2026, 6, 30)
    older = (income_end - timedelta(days=spread)).isoformat()

    assert (landed_check(30, "2026-06-30", balance_end=older) is not None) is fires
    assert (landed_check(30, "2026-06-30", cash_end=older) is not None) is fires


def test_not_landed_anchor_is_the_last_reported_earnings_date():
    flag = landed_check(30, "2026-03-31")

    assert flag.rule == sr.NOT_LANDED and flag.anchor == TODAY - timedelta(days=30) and flag.filing_date is None


def test_not_landed_never_fires_without_a_reported_earnings_date_or_income_row():
    placeholder_only = [{"date": "2026-08-04", "epsActual": None, "revenueActual": None}]
    stale = Statements([income("2026-03-31")], [balance("2026-03-31")], [cash_flow("2026-03-31")], [], placeholder_only)
    assert not_landed_flag(stale, TODAY) is None
    assert not_landed_flag(stale._replace(earnings=[]), TODAY) is None
    assert not_landed_flag(stale._replace(earnings=earnings("2026-08-04"), income_quarterly=[]), TODAY) is None


def test_mrk_shaped_ticker_triggers_before_the_catch_up():
    # MRK: reported 2026-08-04 but every cached statement still ended 2026-03-31 (126 days earlier).
    stale = Statements(
        [income("2026-03-31")], [balance("2026-03-31")], [cash_flow("2026-03-31")], [], earnings("2026-08-04", "2026-04-30")
    )

    assert rules_of(stale) == [sr.NOT_LANDED]
    assert evaluate_rules(stale, None, TODAY).anchor == date(2026, 8, 4)


@pytest.mark.parametrize(
    "name,reported,income_end,balance_end,cash_end",
    [
        ("APO", "2026-08-05", "2026-03-31", "2026-03-31", "2026-03-31"),  # nothing landed
        ("AIZ", "2026-08-05", "2026-06-30", "2026-03-31", "2026-03-31"),  # income landed, balance/cash flow did not
        ("HSIC", "2026-08-04", "2026-03-28", "2026-03-28", "2026-03-28"),
        ("TME", "2026-08-12", "2026-06-30", "2026-03-31", "2026-06-30"),  # only the balance sheet is behind
    ],
)
def test_other_known_not_landed_shapes_trigger(name, reported, income_end, balance_end, cash_end):
    stale = Statements(
        [income(income_end)], [balance(balance_end)], [cash_flow(cash_end)], [], earnings(reported)
    )

    assert sr.NOT_LANDED in rules_of(stale), name


def test_a_ticker_whose_newest_quarter_landed_in_time_does_not_trigger():
    # Reported 35 days after quarter end, all three statements aligned; also a late 10-K filer at 75 days.
    assert landed_check(30, "2026-06-30") is None
    assert not_landed_flag(healthy(earnings=earnings("2026-09-13")), TODAY) is None  # 75 days after 2026-06-30, 22 days ago


def test_a_not_yet_reported_quarter_does_not_trigger():
    # The quarter ended 2026-09-30 but earnings (2026-10-29) are still ahead: nothing is missing.
    statements = healthy(earnings=earnings("2026-08-04") + [{"date": "2026-10-29", "epsActual": None, "revenueActual": None}])

    assert not_landed_flag(statements, TODAY) is None


# ---- priority order ----------------------------------------------------------------


def test_every_tripped_rule_is_reported_and_the_first_in_priority_order_is_the_trigger():
    cf = [cash_flow("2026-03-31", placeholder=True)] + [cash_flow(d) for d in QUARTER_ENDS[2:]]
    bs = [balance("2026-03-31", long=300)] + [balance(d) for d in QUARTER_ENDS[2:]]
    stale = Statements([income("2026-03-31")] + [income(d) for d in QUARTER_ENDS[2:]], bs, cf, [], earnings("2026-08-04"))

    ev = evaluate_rules(stale, None, TODAY)

    assert ev.rules == [sr.PLACEHOLDER_CF, sr.DEBT_REMAP, sr.NOT_LANDED]
    assert ev.trigger == sr.PLACEHOLDER_CF


# ---- state transitions -------------------------------------------------------------


def flagged(anchor, rule=sr.DEBT_REMAP, chronic=False) -> Evaluation:
    return Evaluation(flags=[Flag(rule, anchor, "x")], chronic=chronic)


def test_new_flag_within_the_window_creates_an_active_row():
    state, event = apply_evaluation(None, "ZTS", flagged(date(2026, 9, 20)), TODAY, NOW)

    assert event == "new"
    assert (state.status, state.attempts, state.episodes, state.trigger, state.anchor_date) == (
        ACTIVE, 0, 1, sr.DEBT_REMAP, date(2026, 9, 20)
    )
    assert state.first_flagged_at == NOW and state.rules_tripped == sr.DEBT_REMAP


def test_flag_past_the_window_on_seeding_is_recorded_as_gave_up_never_retried():
    anchor = TODAY - timedelta(days=61)
    state, event = apply_evaluation(None, "ZTS", flagged(anchor), TODAY, NOW)

    assert event == "new" and state.status == GAVE_UP and state.last_result == "seeded_expired"
    assert is_due(state, TODAY + timedelta(days=5)) is False
    # exactly 60 days after the anchor is still inside the window.
    inside, _ = apply_evaluation(None, "ZTS", flagged(TODAY - timedelta(days=60)), TODAY, NOW)
    assert inside.status == ACTIVE


def test_chronic_flag_creates_a_chronic_row_even_past_the_window():
    state, _ = apply_evaluation(None, "HSBC", flagged(TODAY - timedelta(days=200), sr.PLACEHOLDER_CF, chronic=True), TODAY, NOW)

    assert state.status == CHRONIC


def test_no_flag_and_no_state_stays_empty():
    assert apply_evaluation(None, "AAPL", Evaluation(), TODAY, NOW) == (None, "none")


def test_clean_rows_heal_an_active_gave_up_or_chronic_state_and_record_days_from_the_anchor():
    for status in (ACTIVE, GAVE_UP, CHRONIC):
        state = RecheckState(
            ticker="BLK", trigger=sr.PLACEHOLDER_CF, anchor_date=TODAY - timedelta(days=26), first_flagged_at=NOW - timedelta(days=10), status=status
        )

        state, event = apply_evaluation(state, "BLK", Evaluation(), TODAY, NOW)

        assert event == "healed"
        assert (state.status, state.healed_at, state.days_to_heal_from_anchor, state.last_result) == (HEALED, NOW, 26, "healed")
        assert state.rules_tripped == ""


def test_a_healed_row_stays_healed_until_flagged_again():
    healed = RecheckState(ticker="BLK", trigger="x", anchor_date=TODAY, first_flagged_at=NOW, status=HEALED, healed_at=NOW)

    assert apply_evaluation(healed, "BLK", Evaluation(), TODAY, NOW) == (healed, "unchanged")


def test_a_new_flag_on_a_healed_row_starts_a_new_episode_on_the_same_row():
    healed = RecheckState(
        ticker="BLK", trigger="x", anchor_date=date(2026, 1, 1), first_flagged_at=NOW, status=HEALED, healed_at=NOW, attempts=4, episodes=1
    )

    state, event = apply_evaluation(healed, "BLK", flagged(date(2026, 10, 1)), TODAY, NOW)

    assert event == "rearmed" and (state.status, state.attempts, state.episodes, state.healed_at) == (ACTIVE, 0, 2, None)


def test_a_moving_filing_date_within_an_episode_does_not_extend_the_window():
    state = RecheckState(ticker="COF", trigger=sr.DEBT_REMAP, anchor_date=TODAY - timedelta(days=70), first_flagged_at=NOW - timedelta(days=70), status=ACTIVE)

    # Still flagged, but the row's filingDate moved 30 days later (the 10-Q landed): same episode, window already over.
    state, event = apply_evaluation(state, "COF", flagged(TODAY - timedelta(days=40)), TODAY, NOW)

    assert event == "gave_up" and state.status == GAVE_UP and state.anchor_date == TODAY - timedelta(days=70)
    again, event = apply_evaluation(state, "COF", flagged(TODAY - timedelta(days=40)), TODAY, NOW)
    assert event == "unchanged" and again.status == GAVE_UP


def test_an_anchor_more_than_a_window_later_is_a_new_episode_even_for_a_gave_up_row():
    state = RecheckState(ticker="COF", trigger=sr.DEBT_REMAP, anchor_date=date(2026, 6, 1), first_flagged_at=NOW, status=GAVE_UP, episodes=1)

    state, event = apply_evaluation(state, "COF", flagged(date(2026, 8, 7)), TODAY, NOW)  # 67 days later

    assert event == "rearmed" and state.status == ACTIVE and state.episodes == 2


def test_chronic_detection_and_loss_of_it_move_the_status_both_ways():
    state = RecheckState(ticker="X", trigger=sr.PLACEHOLDER_CF, anchor_date=TODAY - timedelta(days=5), first_flagged_at=NOW, status=ACTIVE)

    state, event = apply_evaluation(state, "X", flagged(TODAY - timedelta(days=5), sr.PLACEHOLDER_CF, chronic=True), TODAY, NOW)
    assert (event, state.status) == ("chronic", CHRONIC)

    state, event = apply_evaluation(state, "X", flagged(TODAY - timedelta(days=5), sr.PLACEHOLDER_CF), TODAY, NOW)
    assert state.status == ACTIVE


# ---- cadence -----------------------------------------------------------------------


def active(first_flagged_days_ago=0, anchor_days_ago=1, attempts=0, last_attempt_days_ago=None, status=ACTIVE):
    return RecheckState(
        ticker="T",
        trigger=sr.DEBT_REMAP,
        anchor_date=TODAY - timedelta(days=anchor_days_ago),
        first_flagged_at=datetime.combine(TODAY - timedelta(days=first_flagged_days_ago), datetime.min.time()),
        attempts=attempts,
        last_attempt_at=None
        if last_attempt_days_ago is None
        else datetime.combine(TODAY - timedelta(days=last_attempt_days_ago), datetime.min.time()),
        status=status,
    )


def test_a_ticker_seeded_from_an_older_cache_is_due_on_the_night_it_is_first_flagged():
    assert is_due(active(first_flagged_days_ago=0), TODAY) is True


def test_a_first_recheck_waits_a_night_when_the_normal_pass_just_refetched_the_rows():
    assert is_due(active(first_flagged_days_ago=0), TODAY, fetched_today=True) is False
    assert is_due(active(first_flagged_days_ago=1), TODAY, fetched_today=False) is True
    # Once an attempt has been counted the flag no longer matters.
    assert is_due(active(first_flagged_days_ago=3, attempts=1, last_attempt_days_ago=1), TODAY, fetched_today=True) is True


def test_seven_daily_attempts_then_every_third_night_until_the_window_ends():
    anchor_ago = 1
    first = TODAY
    state = active(first_flagged_days_ago=0, anchor_days_ago=anchor_ago)
    due_days = []
    for offset in range(0, 61):
        night = first + timedelta(days=offset)
        if night > sr.window_end(state.anchor_date):
            assert is_due(state, night) is False  # past the window: never due
            continue
        if is_due(state, night):
            due_days.append(offset)
            state.attempts += 1
            state.last_attempt_at = datetime.combine(night, datetime.min.time())

    assert due_days[:7] == [0, 1, 2, 3, 4, 5, 6]
    assert due_days[7:12] == [9, 12, 15, 18, 21]
    assert max(due_days) <= (sr.window_end(state.anchor_date) - first).days


def test_a_night_already_attempted_today_is_not_due_again():
    assert is_due(active(first_flagged_days_ago=3, attempts=2, last_attempt_days_ago=0), TODAY) is False


def test_the_window_closes_60_days_after_the_anchor():
    assert is_due(active(first_flagged_days_ago=5, anchor_days_ago=60, attempts=1, last_attempt_days_ago=1), TODAY) is True
    assert is_due(active(first_flagged_days_ago=5, anchor_days_ago=61, attempts=1, last_attempt_days_ago=1), TODAY) is False


def test_a_missed_night_is_made_up_while_attempts_are_below_seven():
    assert is_due(active(first_flagged_days_ago=9, attempts=3, last_attempt_days_ago=5), TODAY) is True


def test_after_seven_attempts_the_next_one_waits_three_days():
    assert is_due(active(first_flagged_days_ago=12, attempts=7, last_attempt_days_ago=2), TODAY) is False
    assert is_due(active(first_flagged_days_ago=12, attempts=7, last_attempt_days_ago=3), TODAY) is True


def test_healed_and_gave_up_rows_are_never_due():
    assert is_due(active(first_flagged_days_ago=5, status=HEALED), TODAY) is False
    assert is_due(active(first_flagged_days_ago=5, status=GAVE_UP), TODAY) is False


def test_chronic_rows_are_rechecked_once_then_at_most_once_a_year():
    assert is_due(active(first_flagged_days_ago=1, status=CHRONIC, anchor_days_ago=300), TODAY) is True  # the one initial check
    assert is_due(active(first_flagged_days_ago=100, status=CHRONIC, anchor_days_ago=300, attempts=1, last_attempt_days_ago=364), TODAY) is False
    assert is_due(active(first_flagged_days_ago=400, status=CHRONIC, anchor_days_ago=300, attempts=1, last_attempt_days_ago=365), TODAY) is True
    assert is_due(active(first_flagged_days_ago=0, status=CHRONIC, anchor_days_ago=300), TODAY, fetched_today=True) is False


# ---- scan_tickers: reads the cache, writes RecheckState, never the cache ------------------------


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(session, ticker, statements: Statements, sector="Technology", industry="Software"):
    fetched = datetime(2026, 9, 1)
    rows = {
        ("income_statement", "quarterly"): statements.income_quarterly,
        ("balance_sheet_statement", "quarterly"): statements.balance_quarterly,
        ("cash_flow_statement", "quarterly"): statements.cash_flow_quarterly,
        ("cash_flow_statement", "annual"): statements.cash_flow_annual,
        ("earnings", "latest"): statements.earnings,
        ("profile", "latest"): [{"sector": sector, "industry": industry}],
    }
    for (statement_type, period), payload in rows.items():
        session.add(FundamentalsCache(ticker=ticker, statement_type=statement_type, period=period, fetched_at=fetched, raw_json=json.dumps(payload)))
    session.commit()


def test_scan_seeds_flagged_tickers_and_leaves_healthy_ones_alone():
    engine = _engine()
    bad_bs = [balance("2026-06-30", long=300)] + [balance(d) for d in QUARTER_ENDS[1:]]
    old_bs = [balance("2026-06-30", long=300, filing="2026-06-01")] + [balance(d) for d in QUARTER_ENDS[1:]]
    with Session(engine) as session:
        _seed(session, "OKAY", healthy())
        _seed(session, "ZTS", healthy(balance_quarterly=bad_bs))
        _seed(session, "OLD", healthy(balance_quarterly=old_bs))

        results = {r.ticker: r for r in scan_tickers(session, ["OKAY", "ZTS", "OLD"], today=TODAY, now=NOW)}

        assert results["OKAY"].state is None and results["OKAY"].event == "none"
        assert results["ZTS"].event == "new" and session.get(RecheckState, "ZTS").status == ACTIVE
        assert session.get(RecheckState, "OLD").status == GAVE_UP  # anchor 2026-06-01 is 126 days old
        assert session.get(RecheckState, "OKAY") is None


def test_scan_heals_a_row_when_the_cached_rows_are_clean_again_and_is_idempotent():
    engine = _engine()
    with Session(engine) as session:
        _seed(session, "ZTS", healthy(balance_quarterly=[balance("2026-06-30", long=300)] + [balance(d) for d in QUARTER_ENDS[1:]]))
        scan_tickers(session, ["ZTS"], today=TODAY, now=NOW)
        assert scan_tickers(session, ["ZTS"], today=TODAY, now=NOW)[0].event == "unchanged"

        cached = session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "balance_sheet_statement")).one()
        cached.raw_json = json.dumps([balance(d) for d in QUARTER_ENDS])
        session.add(cached)
        session.commit()

        later = NOW + timedelta(days=3)
        result = scan_tickers(session, ["ZTS"], today=later.date(), now=later)[0]

        state = session.get(RecheckState, "ZTS")
        assert result.event == "healed"
        assert (state.status, state.days_to_heal_from_anchor) == (HEALED, (later.date() - date(2026, 8, 7)).days)


def test_scan_without_persist_writes_nothing_and_never_modifies_the_cache():
    engine = _engine()
    with Session(engine) as session:
        _seed(session, "ZTS", healthy(balance_quarterly=[balance("2026-06-30", long=300)] + [balance(d) for d in QUARTER_ENDS[1:]]))
        before = [(r.id, r.fetched_at, r.raw_json) for r in session.exec(select(FundamentalsCache)).all()]

        results = scan_tickers(session, ["ZTS"], today=TODAY, now=NOW, persist=False)

        assert results[0].event == "new"
        assert session.get(RecheckState, "ZTS") is None
        assert [(r.id, r.fetched_at, r.raw_json) for r in session.exec(select(FundamentalsCache)).all()] == before


def test_statements_fetched_on_checks_only_the_three_quarterly_rows():
    engine = _engine()
    with Session(engine) as session:
        _seed(session, "ZTS", healthy())  # every row stamped 2026-09-01
        assert sr.statements_fetched_on(session, "ZTS", date(2026, 9, 1)) is True
        assert sr.statements_fetched_on(session, "ZTS", date(2026, 10, 5)) is False
        income_q = session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "income_statement", FundamentalsCache.period == "quarterly")).one()
        income_q.fetched_at = datetime(2026, 10, 5, 2, 10)
        session.add(income_q)
        session.commit()
        assert sr.statements_fetched_on(session, "ZTS", date(2026, 10, 5)) is True


def test_scan_uses_the_cached_profile_for_the_debt_basis():
    engine = _engine()
    bs = [balance("2026-06-30", long=300, total_debt=1000)] + [balance(d) for d in QUARTER_ENDS[1:]]
    with Session(engine) as session:
        _seed(session, "STD", healthy(balance_quarterly=bs))
        _seed(session, "REIT", healthy(balance_quarterly=bs), sector="Real Estate", industry="REIT - Diversified")

        results = {r.ticker: r.evaluation.rules for r in scan_tickers(session, ["STD", "REIT"], today=TODAY, now=NOW)}

    assert results == {"STD": [sr.DEBT_REMAP], "REIT": []}
