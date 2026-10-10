"""The `data_quality` markers on the Financials, Ratios, summary, Step 4 and Step 5 payloads (helpers/statement_view.py::
cached_data_quality, docs/specs/statement-data-quality.md "Display markers"). Cache-only reads over a seeded in-memory engine
(CLAUDE.md's rule: every module's own `engine` reference is repointed). FMP is never called."""

import asyncio
import json
import sys
from datetime import datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, delete

import core.db as core_db
from conftest import real_engine as _real_core_engine  # core.db.engine itself is isolated per test (conftest._isolate_core_db_engine)
import data.financials_data as financials_data
import data.ratios_data as ratios_data
import data.step4_data as step4_data
import data.step5_data as step5_data
import data.ticker_summary as ticker_summary
from core.models import FundamentalsCache
from helpers.statement_view import cached_data_quality
from test_statement_recheck import QUARTER_ENDS, balance, cash_flow, earnings, income

PROFILE = [{"sector": "Technology", "industry": "Consumer Electronics", "companyName": "Acme"}]
CASH_FLOW_ANNUAL_TYPE = ("cash_flow_statement", "annual")


@pytest.fixture
def engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    real = _real_core_engine
    for module in list(sys.modules.values()):
        if module is not core_db and getattr(module, "engine", None) is real:
            monkeypatch.setattr(module, "engine", test_engine)
    monkeypatch.setattr(core_db, "engine", test_engine)
    return test_engine


def labelled(rows):
    """Give every quarterly row the period / fiscalYear labels FMP serves (the Financials columns are labelled "Q2 2026")."""
    return [
        {**row, "period": f"Q{(int(row['date'][5:7]) - 1) // 3 + 1}", "fiscalYear": row["date"][:4]} if len(row.get("date", "")) == 10 else row
        for row in rows
    ]


def seed(engine, ticker="TEST", *, income_q=None, balance_q=None, cash_flow_q=None, cash_flow_a=None, earnings_rows=None):
    payloads = {
        ("profile", "latest"): PROFILE,
        ("income_statement", "quarterly"): labelled(income_q if income_q is not None else [income(d) for d in QUARTER_ENDS]),
        ("income_statement", "annual"): [],
        ("balance_sheet_statement", "quarterly"): labelled(balance_q if balance_q is not None else [balance(d) for d in QUARTER_ENDS]),
        ("balance_sheet_statement", "annual"): [],
        ("cash_flow_statement", "quarterly"): labelled(cash_flow_q if cash_flow_q is not None else [cash_flow(d) for d in QUARTER_ENDS]),
        CASH_FLOW_ANNUAL_TYPE: cash_flow_a if cash_flow_a is not None else [],
        ("earnings", "latest"): earnings_rows if earnings_rows is not None else earnings("2026-08-04", "2026-05-05"),
    }
    with Session(engine) as session:
        session.exec(delete(FundamentalsCache).where(FundamentalsCache.ticker == ticker))
        for (statement_type, period), payload in payloads.items():
            session.add(
                FundamentalsCache(
                    ticker=ticker, statement_type=statement_type, period=period, fetched_at=datetime.now(), raw_json=json.dumps(payload)
                )
            )
        session.commit()


PLACEHOLDER_CF = [cash_flow("2026-06-30", placeholder=True)] + [cash_flow(d) for d in QUARTER_ENDS[1:]]
PARTIAL_BALANCE = [balance("2026-06-30", long=300)] + [balance(d) for d in QUARTER_ENDS[1:]]


def rules(flags):
    return sorted(f.rule for f in flags)


# ---- the four rules reach the payloads ---------------------------------------------------------------------------


def test_financials_flags_a_placeholder_quarter_with_the_column_it_sits_in(engine):
    seed(engine, cash_flow_q=PLACEHOLDER_CF)

    payload = asyncio.run(financials_data.get_financials_data("TEST", cache_only=True))

    assert rules(payload.data_quality) == ["placeholder_cf"]
    flag = payload.data_quality[0]
    assert (flag.statement, flag.period, flag.period_end, flag.column) == ("cash_flow", "quarterly", "2026-06-30", "Q2 2026")
    assert flag.detail["in_ttm_window"] is True and flag.detail["newest_period"] is True
    # the label really is one of the table's own headers
    assert flag.column in payload.cash_flow.quarterly.periods


def test_financials_flags_a_partial_balance_sheet_on_the_newest_quarter_column(engine):
    seed(engine, balance_q=PARTIAL_BALANCE)

    payload = asyncio.run(financials_data.get_financials_data("TEST", cache_only=True))

    assert rules(payload.data_quality) == ["partial_balance_sheet"]
    flag = payload.data_quality[0]
    assert (flag.statement, flag.period_end, flag.column) == ("balance_sheet", "2026-06-30", "Q2 2026")
    assert flag.detail["used_quarter_date"] == "2026-03-31" and flag.detail["reason"] == "debt_remap"


def test_financials_flags_a_scale_broken_annual_cash_flow_row_on_its_annual_column(engine):
    from test_ttm import _row

    annual = [{**_row(scale=1e-6, growth=1.6), "date": "2026-06-30", "period": "FY", "fiscalYear": "2026"}] + [
        {**_row(growth=1.0 + 0.05 * i), "date": f"{2025 - i}-06-30", "period": "FY", "fiscalYear": str(2025 - i)} for i in range(5)
    ]
    seed(engine, cash_flow_a=annual)

    payload = asyncio.run(financials_data.get_financials_data("TEST", cache_only=True))

    scale = [f for f in payload.data_quality if f.rule == "scale_break" and f.period == "annual"]
    assert [(f.period_end, f.column) for f in scale] == [("2026-06-30", "2026-06-30")]
    assert "2026-06-30" in payload.cash_flow.annual.periods


def test_not_landed_is_reported_once_and_marks_no_column(engine):
    ends = QUARTER_ENDS[1:]  # Q2 reported 2026-08-04, newest cached quarter ends 2026-03-31
    seed(
        engine,
        income_q=[income(d) for d in ends],
        balance_q=[balance(d) for d in ends],
        cash_flow_q=[cash_flow(d) for d in ends],
    )

    payload = asyncio.run(financials_data.get_financials_data("TEST", cache_only=True))

    assert rules(payload.data_quality) == ["not_landed"]
    assert payload.data_quality[0].detail["reported_on"] == "2026-08-04"
    assert payload.data_quality[0].column is None or payload.data_quality[0].column in payload.income_statement.quarterly.periods


def test_a_healthy_ticker_has_no_flags_on_any_payload(engine):
    seed(engine)

    assert asyncio.run(financials_data.get_financials_data("TEST", cache_only=True)).data_quality == []
    assert asyncio.run(ratios_data.get_ratios_data("TEST", cache_only=True)).data_quality == []
    assert asyncio.run(step4_data.get_step4_data("TEST", cache_only=True)).data_quality == []
    assert asyncio.run(step5_data.get_step5_data("TEST", cache_only=True)).data_quality == []
    assert asyncio.run(ticker_summary.get_summary("TEST", cache_only=True)).data_quality == []


# ---- every payload carries them ------------------------------------------------------------------------------------


def test_ratios_summary_step4_and_step5_carry_the_same_flags(engine):
    seed(engine, balance_q=PARTIAL_BALANCE, cash_flow_q=PLACEHOLDER_CF)
    expected = ["partial_balance_sheet", "placeholder_cf"]

    assert rules(asyncio.run(ratios_data.get_ratios_data("TEST", cache_only=True)).data_quality) == expected
    assert rules(asyncio.run(step4_data.get_step4_data("TEST", cache_only=True)).data_quality) == expected
    step5 = asyncio.run(step5_data.get_step5_data("TEST", cache_only=True))
    assert rules(step5.data_quality) == expected
    assert step5.balance_sheet_fallback.used_quarter_date == "2026-03-31"  # the structured fallback is unchanged
    assert rules(asyncio.run(ticker_summary.get_summary("TEST", cache_only=True)).data_quality) == expected


def test_step4_marks_a_placeholder_on_the_newest_period_for_the_ratios_note(engine):
    seed(engine, cash_flow_q=PLACEHOLDER_CF)

    flags = asyncio.run(step4_data.get_step4_data("TEST", cache_only=True)).data_quality

    assert [(f.rule, f.detail["newest_period"]) for f in flags] == [("placeholder_cf", True)]


def test_a_placeholder_on_an_old_quarter_is_flagged_but_not_marked_newest(engine):
    ends = QUARTER_ENDS + ["2024-12-31"]
    seed(
        engine,
        income_q=[income(d) for d in ends],
        cash_flow_q=[cash_flow(d) for d in ends[:-1]] + [cash_flow("2024-12-31", placeholder=True)],
    )

    flags = asyncio.run(step4_data.get_step4_data("TEST", cache_only=True)).data_quality

    assert [(f.rule, f.period_end, f.detail["newest_period"], f.detail["in_ttm_window"]) for f in flags] == [
        ("placeholder_cf", "2024-12-31", False, False)
    ]


# ---- values are untouched, markers vanish on heal ------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: financials_data.get_financials_data("TEST", cache_only=True),
        lambda: ratios_data.get_ratios_data("TEST", cache_only=True),
        lambda: step4_data.get_step4_data("TEST", cache_only=True),
        lambda: step5_data.get_step5_data("TEST", cache_only=True),
        lambda: ticker_summary.get_summary("TEST", cache_only=True),
    ],
    ids=["financials", "ratios", "step4", "step5", "summary"],
)
def test_every_value_in_the_payload_is_identical_with_and_without_the_markers(engine, monkeypatch, build):
    seed(engine, balance_q=PARTIAL_BALANCE, cash_flow_q=PLACEHOLDER_CF)

    with_flags = asyncio.run(build())
    assert with_flags.data_quality  # markers are on
    for module in (financials_data, ratios_data, step4_data, step5_data, ticker_summary):
        monkeypatch.setattr(module, "cached_data_quality", lambda session, ticker, today=None: [], raising=False)
    without_flags = asyncio.run(build())

    assert without_flags.data_quality == []
    assert json.dumps(with_flags.model_dump(exclude={"data_quality"}), sort_keys=True, default=str) == json.dumps(
        without_flags.model_dump(exclude={"data_quality"}), sort_keys=True, default=str
    )


def test_markers_disappear_once_the_cached_rows_heal(engine):
    seed(engine, balance_q=PARTIAL_BALANCE, cash_flow_q=PLACEHOLDER_CF)
    with Session(engine) as session:
        assert rules(cached_data_quality(session, "TEST")) == ["partial_balance_sheet", "placeholder_cf"]

    seed(engine)  # the refetch healed both rows

    with Session(engine) as session:
        assert cached_data_quality(session, "TEST") == []
    assert asyncio.run(financials_data.get_financials_data("TEST", cache_only=True)).data_quality == []
