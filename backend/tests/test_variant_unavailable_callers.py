"""Every caller of a request variant the plan can refuse (period=quarter statements, quarterly ratios/key-metrics,
quarterly enterprise values, quarterly as-reported) degrades without raising and without caching an empty row, when
FMPClient answers that variant with FMPVariantUnavailableError (core/data_groups.py "Request variants").

Each scenario reuses the happy-path harness of the caller's own test module (its fake FMP data and engine isolation),
then makes every `period="quarter"` request unavailable and records what the caller now shows. The assertions are
the "what each caller shows" table in docs/specs/fmp-data-and-bar-cache.md, the input to the later Step 5 annual
fallback task -- they document current behaviour, they do not endorse it (scoring is deliberately NOT fixed here).

Imports sibling test modules by basename (tests/ has no __init__; pytest's default import mode puts it on sys.path)."""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import core.cache as cache_module
import data.financials_data as financials_data
import test_financials_data as t_fin
import test_ratios_data as t_rat
import test_speculative_growth_data as t_spec
import test_step1_data as t_s1
import test_step3_data as t_s3
import test_step4_data as t_s4
import test_step5_data as t_s5
import test_ticker_summary as t_sum
from clients.fmp_client import FMPVariantUnavailableError, fmp_client
from core.models import FundamentalsCache

QUARTERLY_PERIODS = {"quarterly", "quarter"}


@pytest.fixture
def written(monkeypatch):
    """Every (statement_type, period, payload) core.cache really stored during the test."""
    log: list[tuple[str, str, object]] = []
    real = cache_module._write_cache_row

    def spy(session, ticker, statement_type, period, data, fetched_at):
        log.append((statement_type, period, data))
        return real(session, ticker, statement_type, period, data, fetched_at)

    monkeypatch.setattr(cache_module, "_write_cache_row", spy)
    return log


def _make_quarter_unavailable(monkeypatch):
    def wrap(name):
        original = getattr(fmp_client, name)

        async def wrapper(ticker, *args, **kwargs):
            period = args[0] if args else kwargs.get("period", "annual")
            if period == "quarter":
                raise FMPVariantUnavailableError("not available on this plan", "fundamentals", "/x?period=quarter", "Quarterly x")
            return await original(ticker, *args, **kwargs)

        monkeypatch.setattr(fmp_client, name, wrapper)

    for name in (
        "get_income_statement", "get_cash_flow_statement", "get_balance_sheet_statement",
        "get_key_metrics", "get_ratios", "get_financial_statement_full_as_reported",
    ):
        wrap(name)

    async def no_quarterly_ev(ticker, period="quarter", limit=1):
        raise FMPVariantUnavailableError("not available on this plan", "fundamentals", "/enterprise-values?limit=1&period=quarter", "Quarterly EV")

    monkeypatch.setattr(fmp_client, "get_enterprise_values", no_quarterly_ev)


def _assert_nothing_quarterly_was_cached(written):
    assert [(t, p) for t, p, _ in written if p in QUARTERLY_PERIODS] == []  # an unavailable variant stores nothing, not even an empty row


def test_step1_ttm_cell_is_blank_and_the_score_is_unchanged(monkeypatch, written):
    t_s1._fresh_engine(monkeypatch)
    t_s1._patch_fmp(monkeypatch, defaultdict(int))
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_s1.get_step1_data("aapl"))
    assert result.years == ["2023", "2024", "2025", "TTM"]  # the column stays...
    assert result.revenue == [200.0, 250.0, 300.0, None]  # ...its cell is blank
    assert result.cfo[-1] is None and result.net_income[-1] is None
    # Scored on the annual points: 100, held to 90 / Pass by the thin-history cap (H1: 3 points, under 8).
    assert (result.score, result.verdict) == (90, "Pass")
    _assert_nothing_quarterly_was_cached(written)


def test_step4_ttm_values_blank_ccc_loses_its_ttm_point_roe_ttm_survives(monkeypatch, written):
    t_s4._fresh_engine(monkeypatch)
    t_s4._patch_fmp(monkeypatch)
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_s4.get_step4_data("aapl"))
    assert result.years[-1] == "TTM"
    assert result.revenue[-1] is None  # TTM revenue / NI / COGS / OCF / buybacks and the balance-sheet snapshots
    assert len(result.ccc) == len(result.years) - 1  # CCC has no TTM point
    assert result.roe[-1] == 20.0  # ROE/ROIC TTM come from /key-metrics-ttm, which is not a period=quarter request
    assert (result.score, result.verdict) == (76, "Pass")
    _assert_nothing_quarterly_was_cached(written)


def test_step5_standard_ticker_is_insufficient_data(monkeypatch, written):
    t_s5._fresh_engine(monkeypatch)
    t_s5._patch_fmp(monkeypatch)
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_s5.get_step5_data("aapl"))
    assert result.verdict == "insufficient_data" and result.score is None  # the whole input is the quarterly balance sheet
    _assert_nothing_quarterly_was_cached(written)


def test_step3_valuation_is_flagged_insufficient_data(monkeypatch, written):
    t_s3._fresh_engine(monkeypatch)
    t_s3._patch_real_data(monkeypatch)
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_s3.get_step3_data("TEST"))
    assert result.insufficient_data is True and result.intrinsic_value_per_share is None
    _assert_nothing_quarterly_was_cached(written)


def test_ratios_tab_ttm_column_loses_its_date_label(monkeypatch, written):
    t_rat._fresh_engine(monkeypatch)
    t_rat._patch_fmp(monkeypatch)
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_rat.get_ratios_data("aapl"))
    assert result.periods[-3:] == ["2024", "2025", "TTM"]  # "TTM (2026-06-27)" -> "TTM": values come from the TTM endpoints
    assert len(result.groups) == len(t_rat.CATEGORIES)
    _assert_nothing_quarterly_was_cached(written)


def test_speculative_growth_loses_the_quarterly_only_fields(monkeypatch, written):
    engine = t_spec._fresh_engine(monkeypatch)
    t_spec._patch_fmp(monkeypatch, t_spec.PROFILE_STANDARD, estimates=t_spec.ESTIMATES_STRONG_GROWTH)
    t_spec._set_moat(engine, "TEST", "narrow_moat")
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_spec.get_speculative_growth_data("TEST"))
    assert result.qualifies is True  # (baseline: also True)
    assert result.cfo_recent_direction is None and result.cash_runway_years is None  # baseline: turning_positive / 10.0
    _assert_nothing_quarterly_was_cached(written)


def test_financials_tab_quarterly_tables_and_ttm_column_are_blank(monkeypatch, written):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(financials_data, "engine", engine)

    async def income(t, p, limit):
        return t_fin.FAKE_INCOME_QUARTERLY if p == "quarter" else t_fin.FAKE_INCOME_ANNUAL

    async def cash(t, p, limit):
        return t_fin.FAKE_CASH_FLOW_QUARTERLY if p == "quarter" else t_fin.FAKE_CASH_FLOW_ANNUAL

    async def balance(t, p, limit):
        return t_fin.FAKE_BALANCE_SHEET_QUARTERLY if p == "quarter" else t_fin.FAKE_BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(fmp_client, "get_income_statement", income)
    monkeypatch.setattr(fmp_client, "get_cash_flow_statement", cash)
    monkeypatch.setattr(fmp_client, "get_balance_sheet_statement", balance)
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_fin.get_financials_data("aapl"))
    assert result.income_statement.quarterly.periods[-2:] == ["—", "—"]  # padded, no 12-quarter tables
    first_row = result.income_statement.annual.groups[0].items[0]
    assert first_row.label == "Revenue" and first_row.values[-1] is None and first_row.values[-2] == 400_000_000_000.0
    _assert_nothing_quarterly_was_cached(written)


def test_summary_header_loses_debt_ebitda_interest_ev_and_reported_currency(monkeypatch, written):
    t_sum._fresh_summary_engine(monkeypatch)
    t_sum._cached_close(monkeypatch, t_sum.LAST_CLOSE)

    async def quote(ticker):
        return t_sum.FAKE_QUOTE

    t_sum._patch_all_but_quote(monkeypatch, quote)
    _make_quarter_unavailable(monkeypatch)
    summary = asyncio.run(t_sum.get_summary("aapl"))
    for field in ("enterprise_value", "total_debt", "ebitda_ttm", "interest_expense_ttm", "interest_income_ttm", "reported_currency"):
        assert getattr(summary, field) is None, field
    assert summary.pe_ratio == pytest.approx(36.0)  # P/E (ratios-ttm + last close) and the quote-based header fields survive
    assert summary.shares_outstanding is not None
    _assert_nothing_quarterly_was_cached(written)


def test_good_cached_quarterly_rows_are_served_not_overwritten(monkeypatch):
    """The other half of "no empty row over good data": with real quarterly rows already cached (even stale), the
    caller reads them while the variant is unavailable and the row is left exactly as it was."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(t_s1.step1_data, "engine", engine)
    t_s1._patch_fmp(monkeypatch, defaultdict(int))
    asyncio.run(t_s1.get_step1_data("aapl"))  # warm: annual + quarterly cached
    with Session(engine) as session:
        for row in session.exec(select(FundamentalsCache)).all():
            row.fetched_at = datetime.now() - timedelta(days=400)  # long stale
            session.add(row)
        session.commit()
        before = {(r.statement_type, r.period): (r.raw_json, r.fetched_at) for r in session.exec(select(FundamentalsCache)).all()}
    _make_quarter_unavailable(monkeypatch)
    result = asyncio.run(t_s1.get_step1_data("aapl"))
    assert result.revenue[-1] == 320.0  # the cached quarterly rows still give the TTM point
    with Session(engine) as session:
        after = {(r.statement_type, r.period): (r.raw_json, r.fetched_at) for r in session.exec(select(FundamentalsCache)).all()}
    for key in (("income_statement", "quarterly"), ("cash_flow_statement", "quarterly")):
        assert after[key] == before[key]  # untouched: same payload, not even re-stamped
