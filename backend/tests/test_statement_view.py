"""helpers/statement_view.py: the cleaned-statement loader (build_statement_view, load_statement_view) and the pure
data-quality function. Synthetic rows only; no FMP, every cache test builds its own in-memory engine."""

import asyncio
import json
from datetime import date, datetime

from sqlmodel import Session, SQLModel, create_engine

from core.models import FundamentalsCache
from helpers.balance_sheet_gate import DEBT_BASIS_SHORT_PLUS_LONG, DEBT_BASIS_TOTAL_DEBT
from helpers.statement_view import (
    NOT_LANDED,
    PARTIAL_BALANCE_SHEET,
    PLACEHOLDER_CF,
    SCALE_BREAK,
    RawStatements,
    build_statement_view,
    data_quality_flags,
    debt_basis_for,
    load_statement_view,
)
from test_statement_recheck import QUARTER_ENDS, balance, cash_flow, earnings, income
from test_ttm import _row

TODAY = date(2026, 10, 5)
REIT = "REIT/Property Developer"


def quarterly(builder, ends=QUARTER_ENDS, **kwargs):
    return [builder(d, **kwargs) for d in ends]


def raw(**overrides) -> RawStatements:
    base = dict(
        income_quarterly=quarterly(income),
        cash_flow_quarterly=quarterly(cash_flow),
        balance_sheet_quarterly=quarterly(balance),
    )
    base.update(overrides)
    return RawStatements(**base)


def rules_of(flags):
    return [f.rule for f in flags]


# ---- a clean ticker is a no-op ---------------------------------------------------------------------------


def test_clean_ticker_passes_every_row_through_and_flags_nothing():
    statements = raw()

    view = build_statement_view(statements, None)

    assert view.income_quarterly == statements.income_quarterly
    assert view.cash_flow_quarterly == statements.cash_flow_quarterly
    assert view.balance_sheet_row is statements.balance_sheet_quarterly[0]
    assert view.balance_sheet_fallback is None
    assert view.used.balance_sheet == "2026-06-30"
    assert view.used.income_ttm_end == view.used.cash_flow_ttm_end == "2026-06-30"
    assert data_quality_flags(statements, earnings("2026-08-04", "2026-05-05"), None, TODAY) == []


def test_empty_statements_build_an_empty_view():
    view = build_statement_view(RawStatements(), None)

    assert view.balance_sheet_row == {} and view.balance_sheet_fallback is None
    assert view.income_quarterly == [] and view.cash_flow_quarterly == []
    assert view.ttm("cash_flow", "netCashProvidedByOperatingActivities").total is None


def test_balance_sheet_can_be_left_out_entirely():
    view = build_statement_view(raw(), None, use_balance_sheet=False)

    assert view.balance_sheet_row == {} and view.balance_sheet_fallback is None


# ---- placeholder cash flow -------------------------------------------------------------------------------


def test_placeholder_newest_cash_flow_quarter_is_dropped_so_ttm_covers_the_last_four_valid_quarters():
    cf = [cash_flow("2026-06-30", placeholder=True)] + quarterly(cash_flow, QUARTER_ENDS[1:])
    statements = raw(cash_flow_quarterly=cf)

    view = build_statement_view(statements, None)

    assert [r["date"] for r in view.cash_flow_quarterly] == QUARTER_ENDS[1:]
    assert view.income_quarterly == statements.income_quarterly  # income keeps its real newest quarter
    assert view.used.income_ttm_end == "2026-06-30" and view.used.cash_flow_ttm_end == "2026-03-31"
    assert view.ttm("cash_flow", "netCashProvidedByOperatingActivities").total == 4 * 500.0
    assert statements.cash_flow_quarterly[0]["netCashProvidedByOperatingActivities"] == 0  # cached rows untouched


def test_placeholder_flag_carries_the_net_income_and_is_inside_the_raw_ttm_window():
    cf = [cash_flow("2026-06-30", placeholder=True)] + quarterly(cash_flow, QUARTER_ENDS[1:])

    flags = data_quality_flags(raw(cash_flow_quarterly=cf), earnings("2026-08-04", "2026-05-05"), None, TODAY)

    assert rules_of(flags) == [PLACEHOLDER_CF]
    flag = flags[0]
    assert (flag.statement, flag.period, flag.period_end) == ("cash_flow", "quarterly", "2026-06-30")
    assert flag.detail == {"net_income": 100.0, "in_ttm_window": True, "newest_period": True}
    assert "all cash-flow section totals are 0" in flag.evidence and "100" in flag.evidence


def test_an_old_placeholder_outside_the_four_newest_quarters_is_flagged_but_not_in_the_ttm_window():
    ends = QUARTER_ENDS + ["2024-12-31"]
    cf = quarterly(cash_flow, ends[:-1]) + [cash_flow("2024-12-31", placeholder=True)]

    flags = data_quality_flags(
        raw(income_quarterly=quarterly(income, ends), cash_flow_quarterly=cf), earnings("2026-08-04"), None, TODAY
    )

    assert [(f.rule, f.period_end, f.detail["in_ttm_window"], f.detail["newest_period"]) for f in flags] == [
        (PLACEHOLDER_CF, "2024-12-31", False, False)
    ]


# ---- scale break -----------------------------------------------------------------------------------------


def _line_row(date_, period, year, scale, growth):
    row = {**_row(scale=scale, growth=growth), "date": date_, "period": period, "fiscalYear": year}
    row["netCashProvidedByOperatingActivities"] = 2_000_000_000 * growth * scale
    return row


def amcr_shaped():
    annual = [_line_row("2026-06-30", "FY", "2026", 1e-6, 1.6)] + [
        _line_row(f"{2025 - i}-06-30", "FY", str(2025 - i), 1.0, 1.0 + 0.05 * i) for i in range(5)
    ]
    ends = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    periods = ["Q4", "Q3", "Q2", "Q1", "Q4"]
    years = ["2026", "2026", "2026", "2026", "2025"]
    quarters = [
        {**_row(growth=1.0 + 0.04 * i), "date": d, "period": p, "fiscalYear": y} for i, (d, p, y) in enumerate(zip(ends, periods, years))
    ]
    return annual, quarters, ends


def test_scale_broken_annual_row_is_blanked_in_place_and_its_derived_q4_is_dropped():
    annual, quarters, ends = amcr_shaped()

    view = build_statement_view(RawStatements(cash_flow_annual=annual, cash_flow_quarterly=quarters), None)

    assert len(view.cash_flow_annual) == len(annual)
    assert view.cash_flow_annual[0]["netCashProvidedByOperatingActivities"] is None
    assert [r["date"] for r in view.cash_flow_quarterly] == ends[1:]  # Q4 FY2026 dropped


def test_scale_break_flags_the_annual_row_and_the_poisoned_q4_with_evidence():
    annual, quarters, _ = amcr_shaped()

    flags = data_quality_flags(RawStatements(cash_flow_annual=annual, cash_flow_quarterly=quarters), [], None, TODAY)

    assert [(f.rule, f.period, f.period_end, f.detail["derived_q4"]) for f in flags] == [
        (SCALE_BREAK, "annual", "2026-06-30", False),
        (SCALE_BREAK, "quarterly", "2026-06-30", True),
    ]
    annual_flag = flags[0]
    assert annual_flag.detail["lines"] >= 8
    assert annual_flag.detail["log10_ratio"] < -2.5  # unscaled millions against dollars
    assert flags[1].detail["in_ttm_window"] is True


# ---- balance-sheet gate ------------------------------------------------------------------------------------


def remapped_debt(**kwargs):
    return [balance("2026-06-30", long=300, **kwargs)] + quarterly(balance, QUARTER_ENDS[1:])  # 1000 -> 300 (-70%)


def test_debt_remap_uses_the_prior_quarter_and_records_the_structured_fallback():
    statements = raw(balance_sheet_quarterly=remapped_debt())

    view = build_statement_view(statements, None)

    assert view.balance_sheet_row is statements.balance_sheet_quarterly[1]
    assert view.balance_sheet_row["longTermDebt"] == 1000
    assert view.debt_metrics.total_debt == 1000
    fallback = view.balance_sheet_fallback
    assert (fallback.reason, fallback.incomplete_quarter_date, fallback.used_quarter_date) == (
        "debt_remap",
        "2026-06-30",
        "2026-03-31",
    )
    assert "total debt" in fallback.detail
    assert view.used.balance_sheet == "2026-03-31"


def test_current_assets_remap_falls_back_on_the_standard_path():
    newest = {**balance("2026-06-30"), "totalCurrentAssets": 1_000}  # 5,000 -> 1,000 (-80%), everything else flat

    view = build_statement_view(raw(balance_sheet_quarterly=[newest] + quarterly(balance, QUARTER_ENDS[1:])), None)

    assert view.balance_sheet_fallback.reason == "current_assets_remap"
    assert view.balance_sheet_row["totalCurrentAssets"] == 5_000


def test_reit_path_does_not_check_current_assets():
    newest = {**balance("2026-06-30"), "totalCurrentAssets": 1_000}

    view = build_statement_view(raw(balance_sheet_quarterly=[newest] + quarterly(balance, QUARTER_ENDS[1:])), REIT)

    assert view.balance_sheet_fallback is None and view.balance_sheet_row is newest


def test_debt_basis_follows_the_company_type():
    assert debt_basis_for(REIT) == DEBT_BASIS_TOTAL_DEBT
    assert debt_basis_for("Standard") == DEBT_BASIS_SHORT_PLUS_LONG
    assert debt_basis_for(None) == DEBT_BASIS_SHORT_PLUS_LONG


def test_reit_gate_watches_total_debt_standard_gate_watches_short_plus_long():
    # long-term debt collapses, FMP's totalDebt field (leases etc.) does not
    only_long_term_drops = [balance("2026-06-30", long=300, total_debt=1000)] + quarterly(balance, QUARTER_ENDS[1:])
    # totalDebt collapses, short + long stay put
    only_total_drops = [balance("2026-06-30", long=1000, total_debt=300)] + quarterly(balance, QUARTER_ENDS[1:])

    assert build_statement_view(raw(balance_sheet_quarterly=only_long_term_drops), None).balance_sheet_fallback is not None
    assert build_statement_view(raw(balance_sheet_quarterly=only_long_term_drops), REIT).balance_sheet_fallback is None
    assert build_statement_view(raw(balance_sheet_quarterly=only_total_drops), None).balance_sheet_fallback is None
    assert build_statement_view(raw(balance_sheet_quarterly=only_total_drops), REIT).balance_sheet_fallback is not None


def test_partial_balance_sheet_flag_names_the_dates_and_the_gate_reason():
    flags = data_quality_flags(raw(balance_sheet_quarterly=remapped_debt()), earnings("2026-08-04", "2026-05-05"), None, TODAY)

    assert rules_of(flags) == [PARTIAL_BALANCE_SHEET]
    flag = flags[0]
    assert (flag.statement, flag.period, flag.period_end) == ("balance_sheet", "quarterly", "2026-06-30")
    assert flag.detail == {
        "reason": "debt_remap",
        "incomplete_quarter_date": "2026-06-30",
        "used_quarter_date": "2026-03-31",
        "in_ttm_window": True,
        "newest_period": True,
    }
    assert flag.evidence.startswith("total debt")


# ---- alignment -------------------------------------------------------------------------------------------


def test_income_and_cash_flow_quarters_are_cut_off_at_the_balance_sheet_used():
    view = build_statement_view(raw(balance_sheet_quarterly=remapped_debt()), None)

    assert [r["date"] for r in view.income_quarterly] == QUARTER_ENDS[1:]
    assert [r["date"] for r in view.cash_flow_quarterly] == QUARTER_ENDS[1:]
    assert view.used.income_ttm_end == view.used.cash_flow_ttm_end == "2026-03-31"


def test_a_quarter_within_ten_days_of_the_balance_sheet_used_is_kept():
    ends = ["2026-04-05"] + QUARTER_ENDS[1:]  # newest income/cash-flow row ends 5 days after the balance sheet used
    statements = raw(
        income_quarterly=quarterly(income, ends),
        cash_flow_quarterly=quarterly(cash_flow, ends),
        balance_sheet_quarterly=remapped_debt(),
    )

    view = build_statement_view(statements, None)

    assert view.income_quarterly[0]["date"] == "2026-04-05"
    assert view.cash_flow_quarterly[0]["date"] == "2026-04-05"


def test_alignment_runs_after_the_placeholder_drop():
    cf = [cash_flow("2026-06-30", placeholder=True)] + quarterly(cash_flow, QUARTER_ENDS[1:])

    view = build_statement_view(raw(cash_flow_quarterly=cf, balance_sheet_quarterly=remapped_debt()), None)

    assert [r["date"] for r in view.cash_flow_quarterly] == QUARTER_ENDS[1:]
    assert view.ttm("income", "netIncome").total == 400.0


def test_ttm_figures_follow_the_aligned_quarters():
    income_rows = [income(d, net_income=n) for d, n in zip(QUARTER_ENDS, [1000.0, 10.0, 10.0, 10.0, 10.0, 10.0])]

    gated = build_statement_view(raw(income_quarterly=income_rows, balance_sheet_quarterly=remapped_debt()), None)
    plain = build_statement_view(raw(income_quarterly=income_rows), None)

    assert plain.ttm("income", "netIncome").total == 1030.0
    assert gated.ttm("income", "netIncome").total == 40.0


# ---- not landed ------------------------------------------------------------------------------------------


def test_not_landed_flag_when_the_newest_reported_quarter_is_missing_from_the_statements():
    ends = QUARTER_ENDS[1:]  # newest cached period 2026-03-31, but Q2 was reported on 2026-08-04
    statements = raw(
        income_quarterly=quarterly(income, ends), cash_flow_quarterly=quarterly(cash_flow, ends), balance_sheet_quarterly=quarterly(balance, ends)
    )

    flags = data_quality_flags(statements, earnings("2026-08-04", "2026-05-05"), None, TODAY)

    assert rules_of(flags) == [NOT_LANDED]
    assert flags[0].detail == {"reported_on": "2026-08-04", "in_ttm_window": False, "newest_period": False}
    assert flags[0].period_end == "2026-03-31"
    assert data_quality_flags(statements, [], None, TODAY) == []  # no earnings history: never fires


# ---- loader reads the cache with the production keys --------------------------------------------------------


def test_load_statement_view_reads_the_cached_rows_and_applies_the_rules():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    cf = [cash_flow("2026-06-30", placeholder=True)] + quarterly(cash_flow, QUARTER_ENDS[1:])
    payloads = {
        ("income_statement", "annual"): [],
        ("income_statement", "quarterly"): quarterly(income),
        ("cash_flow_statement", "annual"): [],
        ("cash_flow_statement", "quarterly"): cf,
        ("balance_sheet_statement", "quarterly"): remapped_debt(),
    }
    with Session(engine) as session:
        for (statement_type, period), payload in payloads.items():
            session.add(
                FundamentalsCache(
                    ticker="XYZ", statement_type=statement_type, period=period, fetched_at=datetime.now(), raw_json=json.dumps(payload)
                )
            )
        session.commit()

        view = asyncio.run(
            load_statement_view(
                session, "XYZ", None, most_recent_earnings_date=None, staleness_days=7, cache_only=True
            )
        )

    assert view.balance_sheet_fallback.reason == "debt_remap"
    assert [r["date"] for r in view.cash_flow_quarterly] == QUARTER_ENDS[1:]
    assert view.balance_sheet_annual == []  # not requested


def test_load_statement_view_leaves_unrequested_statements_empty():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        view = asyncio.run(
            load_statement_view(
                session,
                "XYZ",
                None,
                most_recent_earnings_date=None,
                staleness_days=7,
                cache_only=True,
                income=False,
                cash_flow=False,
                balance_sheet=False,
            )
        )

    assert view.income_quarterly == [] and view.cash_flow_quarterly == [] and view.balance_sheet_row == {}
