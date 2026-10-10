"""Tests for data/dashboard_data.py and GET /api/tickers/{t}/dashboard (docs/specs/dashboard.md). The step functions, the summary and
the bars reader are stubbed (the endpoint only assembles their results), on a fresh in-memory engine patched onto every module the
read touches (CLAUDE.md, "Ad-hoc reproduction scripts"). Nothing here may call FMP."""

import asyncio
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.dashboard_data as dd
import data.last_close_data as last_close_data
from analysis.trend_structure.weinstein import WeinsteinParams, compute_weinstein_stage
from core.models import FundamentalsCache, MoatScoreConfig, TickerLastClose, TickerMoat, TickerScore
from core.schemas import ScoredRatioOut, Step1Out, Step2Out, Step3Out, Step4Out, Step5Out, Step5RatioResult, TickerSummaryOut
from scoring.step3 import classify_valuation_verdict
from scoring.step4 import scored_ratio_summary, score_roe, score_roic
from scoring import step5 as s5

YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(dd, "engine", engine)
    monkeypatch.setattr(last_close_data, "engine", engine)
    monkeypatch.setattr(dd, "read_cached_daily_bars_batch", lambda tickers, days, reference=None: {})
    return engine


def seed_profile(engine, ticker="ACME", **profile):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(),
                raw_json=json.dumps([{"sector": "Technology", "industry": "Software - Application", **profile}]),
            )
        )
        session.commit()


# --- stub builders -----------------------------------------------------------------------------------------------------------


def step1(cfo_exempt_reason=None, score=82, verdict="Pass"):
    n = len(YEARS)
    return Step1Out(
        ticker="ACME",
        years=YEARS + ["TTM"],
        revenue=[100.0 + i for i in range(n)] + [200.0],
        net_income=[10.0 + i for i in range(n)] + [20.0],
        operating_income=[1.0] * (n + 1),
        cfo=[12.0 + i for i in range(n)] + [30.0],
        gross_margin=[1.0] * (n + 1),
        net_margin=[1.0] * (n + 1),
        cfo_exempt_reason=cfo_exempt_reason,
        score=score,
        verdict=verdict,
        weights={},
    )


def step4(company_type="Standard", roic=True, roe_scored=None, roic_scored=None):
    years = ["—"] + YEARS + ["TTM"]
    return Step4Out(
        ticker="ACME",
        years=years,
        company_type=company_type,
        roe=[None] + [10.0 + i for i in range(6)] + [20.0],
        roic=([None] + [8.0 + i for i in range(6)] + [18.0]) if roic else None,
        roic_exempt_reason=None if roic else f"ROIC not applicable for {company_type}",
        revenue=[1.0] * 8,
        accounts_receivable=[1.0] * 8,
        roe_scored=roe_scored,
        roic_scored=roic_scored,
        score=71,
        verdict="Pass",
    )


def ratio(value, label="good", points=85, adjusted=None, note=None):
    return Step5RatioResult(value=value, adjusted_value=adjusted, label=label, points=points, note=note)


def step5_standard(**overrides):
    ratios = {
        "current_ratio": ratio(1.8, adjusted=1.8),
        "debt_to_ebitda": ratio(2.5, "acceptable", 70),
        "debt_servicing_ratio": ratio(12.0),
        "interest_coverage_ratio": ratio(9.0, "safe", 0),
    }
    ratios.update(overrides.pop("ratios", {}))
    return Step5Out(ticker="ACME", company_type=overrides.pop("company_type", "Standard"), ratios=ratios, score=80, verdict="Pass", debt_ratios_evaluated=True, **overrides)


def summary(**kw):
    values = dict(
        company_name="Acme", ticker="ACME", sector="Technology", price=90.0, fair_value_price=100.0, fair_value_verdict="undervalued",
        fair_value_method="DCF", valuation_source="auto", quote_currency="USD", reported_currency="USD",
    )
    return TickerSummaryOut(**{**values, **kw})


def patch_steps(monkeypatch, *, s1=None, s2=None, s4=None, s5=None, summ=None, s3=None):
    async def ret(value, *a, **k):
        return value

    monkeypatch.setattr(dd, "get_step1_data", lambda *a, **k: ret(s1))
    monkeypatch.setattr(dd, "get_step2_data", lambda *a, **k: ret(s2))
    monkeypatch.setattr(dd, "get_step4_data", lambda *a, **k: ret(s4))
    monkeypatch.setattr(dd, "get_step5_data", lambda *a, **k: ret(s5))
    monkeypatch.setattr(dd, "get_summary", lambda *a, **k: ret(summ))
    monkeypatch.setattr(dd, "get_active_valuation", lambda *a, **k: ret(s3))


def daily_bars(days=1500, start=50.0, drift=0.0006, end="2026-10-09"):
    index = pd.bdate_range(end=end, periods=days)
    close = start * np.exp(np.cumsum(np.full(days, drift)))
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6}, index=index)


def get(client_ticker="ACME"):
    return TestClient(main.app).get(f"/api/tickers/{client_ticker}/dashboard")


# --- Financials --------------------------------------------------------------------------------------------------------------


def test_financials_standard_scores_all_three_and_drops_ttm():
    block = dd.financials_block(step1(), {"score": 82, "verdict": "Pass", "stored_score": 80, "stored_verdict": "Pass"})
    assert block.series.years == ["2021", "2022", "2023", "2024", "2025"]  # last 5 completed years, no TTM
    assert block.series.revenue == [101.0, 102.0, 103.0, 104.0, 105.0]
    assert block.series.cfo[-1] == 17.0
    assert block.scored_revenue and block.scored_net_income and block.scored_cfo and block.cfo_exempt_reason is None
    assert (block.score, block.verdict, block.stored_score) == (82, "Pass", 80)


@pytest.mark.parametrize("reason", ["Bank", "Insurance", "Property Developer", "Commodity Company"])
def test_financials_exempt_types_score_revenue_and_net_income_only(reason):
    block = dd.financials_block(step1(cfo_exempt_reason=reason), {})
    assert block.scored_revenue and block.scored_net_income and not block.scored_cfo
    assert block.cfo_exempt_reason == reason
    assert block.series.cfo  # shown, not scored


def test_financials_missing_step_is_unavailable():
    block = dd.financials_block(None, {"stored_score": 77, "stored_verdict": "Pass"})
    assert not block.available and block.series.years == [] and block.stored_score == 77


def test_financials_short_history_keeps_what_exists():
    s = step1()
    s.years, s.revenue, s.net_income, s.cfo = ["2024", "2025", "TTM"], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [None, 2.0, 3.0]
    block = dd.financials_block(s, {})
    assert block.series.years == ["2024", "2025"] and block.series.cfo == [None, 2.0]


# --- Growth ------------------------------------------------------------------------------------------------------------------


def test_growth_passes_the_stored_cagr_and_analyst_count():
    s2 = Step2Out(ticker="ACME", growth_rate=14.2, target_analyst_count=23, basis="eps", base_fiscal_year="2025", target_fiscal_year="2028", score=90, verdict="Strong Pass", weights={})
    block = dd.growth_block(s2, {})
    assert block.available and block.growth_rate == 14.2 and block.target_analyst_count == 23 and block.basis == "eps"


def test_growth_without_estimates_is_unavailable():
    block = dd.growth_block(Step2Out(ticker="ACME", verdict="insufficient_data", weights={}), {})
    assert not block.available and block.growth_rate is None


# --- Moat --------------------------------------------------------------------------------------------------------------------


def test_moat_not_rated_is_scored_as_no_moat(db):
    with Session(db) as session:
        out = dd.moat_block(session, "ACME", daily_bars(1500))
    assert out.moat is None and not out.rated and out.multiplier == 0.70


def test_moat_narrow_reads_the_saved_multiplier_and_labels_the_series(db):
    with Session(db) as session:
        session.add(TickerMoat(ticker="ACME", moat="narrow_moat", updated_at=datetime.now()))
        session.add(MoatScoreConfig(key="default", narrow_moat_multiplier=0.82, updated_at=datetime.now()))
        session.commit()
        out = dd.moat_block(session, "ACME", daily_bars(1500))
    assert out.moat == "narrow_moat" and out.rated and out.multiplier == 0.82
    assert out.price_label == "5-year price" and out.price_years_covered > 5.0
    assert 250 < len(out.price_series) < 320  # weekly, not daily
    assert out.price_series[-1].day == date(2026, 10, 9)  # the last real bar date, not the week-end label


def test_moat_short_history_is_labelled_honestly_and_no_bars_is_unavailable(db):
    with Session(db) as session:
        short = dd.moat_block(session, "ACME", daily_bars(500))
        none = dd.moat_block(session, "ACME", None)
    assert short.price_label.startswith("1.9-year price") and short.price_series
    assert none.price_series == [] and none.price_unavailable_reason == "No cached daily bars"


# --- Profitability -----------------------------------------------------------------------------------------------------------


def test_profitability_standard_carries_the_scored_average_and_cutoffs():
    scored = ScoredRatioOut(basis="average", average=14.0, minimum=9.0, points_used=7, points_total=7)
    block = dd.profitability_block(step4(roe_scored=scored, roic_scored=scored), {})
    assert block.roe.years == ["2021", "2022", "2023", "2024", "2025"] and block.roe.scored.average == 14.0
    assert block.roic.exempt_reason is None and block.roic.scored.average == 14.0
    assert (block.cutoffs.excellent, block.cutoffs.good, block.cutoffs.marginal) == (15.0, 12.0, 8.0)


@pytest.mark.parametrize("company_type", ["Bank", "Insurance", "Utility", "REIT/Property Developer"])
def test_profitability_roic_is_not_applicable_for_exempt_types(company_type):
    block = dd.profitability_block(step4(company_type=company_type, roic=False), {})
    assert block.roic.exempt_reason and block.roic.values == [] and block.roe.values


def test_scored_average_is_the_average_the_tier_reads():
    # A spike year is left out of the average and the recovery-aware prefix is skipped: the summary must equal what the scorer tiers on.
    series = [11.0, 12.0, 13.0, 12.5, 60.0, 13.5]
    summary_ = scored_ratio_summary(series)
    assert summary_.spike_excluded and summary_.average == pytest.approx(np.mean([11.0, 12.0, 13.0, 12.5, 13.5]))
    assert score_roic(series).label == "good"  # avg 12.4 with the spike left out
    assert scored_ratio_summary([None, 0.0]) is None


def test_scored_average_flags_the_recovery_exclusion():
    series = [30.0, 28.0, 2.0, 25.0, 26.0, 27.0]
    summary_ = scored_ratio_summary(series)
    assert summary_.points_total == 6 and summary_.points_used + summary_.recovery_excluded == 6
    assert score_roe(series, [1.0] * 6, [1.0] * 6).label in {"excellent", "good", "marginal"}


# --- Debt --------------------------------------------------------------------------------------------------------------------


def test_debt_lines_come_from_the_scoring_constants():
    block = dd.debt_block(step5_standard(), {})
    by_key = {r.key: r for r in block.ratios}
    assert list(by_key) == ["current_ratio", "debt_to_ebitda", "debt_servicing_ratio"]  # interest coverage is not a gauge
    assert (by_key["current_ratio"].direction, by_key["current_ratio"].pass_line, by_key["current_ratio"].hard_limit) == ("floor", s5.CURRENT_RATIO_COMFORTABLE, s5.CURRENT_RATIO_SEVERE)
    assert (by_key["debt_to_ebitda"].direction, by_key["debt_to_ebitda"].pass_line, by_key["debt_to_ebitda"].hard_limit) == ("ceiling", s5.DEBT_EBITDA_COMFORTABLE, s5.DEBT_EBITDA_SEVERE)
    assert (by_key["debt_servicing_ratio"].unit, by_key["debt_servicing_ratio"].pass_line, by_key["debt_servicing_ratio"].hard_limit) == ("pct", s5.DSR_COMFORTABLE, s5.DSR_SEVERE)
    assert block.status == "scored" and by_key["current_ratio"].adjusted_value is None


def test_debt_current_ratio_shows_the_deferred_revenue_adjusted_value_only_when_it_differs():
    block = dd.debt_block(step5_standard(ratios={"current_ratio": ratio(0.8, "good", 85, adjusted=1.2)}), {})
    cr = block.ratios[0]
    assert cr.value == 0.8 and cr.adjusted_value == 1.2


def test_debt_servicing_excluded_for_non_positive_cash_flow_and_negative_ebitda_has_no_value():
    out = step5_standard(
        ratios={
            "debt_servicing_ratio": ratio(None, "excluded_negative_cfo", 0, note="excluded"),
            "debt_to_ebitda": ratio(None, "negative_ebitda", 0, note="negative"),
        },
        unrescued_breaches=["debt_to_ebitda"],
    )
    block = dd.debt_block(out, {})
    by_key = {r.key: r for r in block.ratios}
    assert by_key["debt_servicing_ratio"].excluded and by_key["debt_servicing_ratio"].value is None
    assert by_key["debt_to_ebitda"].value is None and by_key["debt_to_ebitda"].tier == "negative_ebitda"
    assert block.unrescued_breaches == ["debt_to_ebitda"]


def test_debt_utility_uses_the_standard_ratios():
    assert len(dd.debt_block(step5_standard(company_type="Utility"), {}).ratios) == 3


def test_debt_reit_gearing_has_one_line():
    out = Step5Out(ticker="ACME", company_type="REIT/Property Developer", ratios={"gearing_ratio": ratio(38.0)}, score=85, verdict="Pass")
    block = dd.debt_block(out, {})
    assert [r.key for r in block.ratios] == ["gearing_ratio"]
    g = block.ratios[0]
    assert g.direction == "ceiling" and g.pass_line == g.hard_limit == s5.GEARING_LIMIT_PCT == 45.0


def test_debt_bank_with_both_ratios_and_with_one_missing():
    full = Step5Out(ticker="ACME", company_type="Bank", ratios={"cet1_ratio": ratio(13.0), "npl_ratio": ratio(0.8, "excellent", 100)}, score=90, verdict="Pass", bank_capital_metrics_editable=True, cet1_ratio_pct=13.0)
    block = dd.debt_block(full, {})
    by_key = {r.key: r for r in block.ratios}
    assert block.status == "scored"
    assert (by_key["cet1_ratio"].direction, by_key["cet1_ratio"].pass_line) == ("floor", s5.CET1_FLOOR_PCT)
    assert (by_key["npl_ratio"].direction, by_key["npl_ratio"].pass_line) == ("ceiling", s5.NPL_LIMIT_PCT)

    partial = Step5Out(ticker="ACME", company_type="Bank", ratios={"npl_ratio": ratio(0.8, "excellent", 100)}, verdict="not_supported", bank_capital_metrics_editable=True)
    block = dd.debt_block(partial, {})
    assert block.status == "partial" and block.status_reason
    assert {r.key: r.value for r in block.ratios} == {"cet1_ratio": None, "npl_ratio": 0.8}


def test_debt_bank_without_deposits_and_insurance_are_not_applicable():
    ibkr = Step5Out(ticker="IBKR", company_type="Bank", verdict="not_supported", classification_note="broker-dealer")
    assert dd.debt_block(ibkr, {}).status == "not_applicable"
    insurer = Step5Out(ticker="PGR", company_type="Insurance", verdict="not_supported")
    block = dd.debt_block(insurer, {})
    assert block.status == "not_applicable" and block.ratios == [] and "insurers" in block.status_reason


def test_debt_insufficient_data_and_missing_step():
    assert dd.debt_block(Step5Out(ticker="ACME", company_type="Standard", verdict="insufficient_data"), {}).status == "insufficient_data"
    assert not dd.debt_block(None, {}).available


def test_debt_single_line_constants_match_the_scorers():
    assert s5.score_gearing(s5.GEARING_LIMIT_PCT).hard_fail is False and s5.score_gearing(s5.GEARING_LIMIT_PCT + 0.01).hard_fail is True
    assert s5.score_npl(s5.NPL_LIMIT_PCT - 0.01).hard_fail is False and s5.score_npl(s5.NPL_LIMIT_PCT).hard_fail is True
    assert s5.score_cet1(s5.CET1_FLOOR_PCT).hard_fail is False and s5.score_cet1(s5.CET1_FLOOR_PCT - 0.01).hard_fail is True
    assert s5.score_current_ratio(s5.CURRENT_RATIO_COMFORTABLE, s5.CURRENT_RATIO_COMFORTABLE).hard_fail is False
    assert s5.score_debt_to_ebitda(s5.DEBT_EBITDA_COMFORTABLE).hard_fail is False and s5.score_debt_to_ebitda(s5.DEBT_EBITDA_COMFORTABLE + 0.01).hard_fail is True


# --- Fair value --------------------------------------------------------------------------------------------------------------


def test_fair_value_band_is_the_valuation_verdict_band(db):
    out = asyncio.run(dd.fair_value_block("ACME", summary(price=90.0, fair_value_price=100.0)))
    assert (out.band_low, out.band_high) == (0.9, 1.1)
    assert classify_valuation_verdict(round(out.band_low - 1, 6)) == "undervalued" and classify_valuation_verdict(round(out.band_high - 1, 6)) == "overvalued"
    assert out.available and out.discount_premium_pct == pytest.approx(-10.0) and out.method == "DCF" and out.currency == "USD"


def test_fair_value_pass_method_and_insufficient_data_give_a_reason(db, monkeypatch):
    async def ret(value, *a, **k):
        return value

    pass_out = Step3Out.model_construct(selected_method="PASS", pass_reason="Losses and no P/B route", insufficient_data=False)
    thin_out = Step3Out.model_construct(selected_method="PASS", pass_reason="Too little history", insufficient_data=True)
    no_value = summary(fair_value_price=None, fair_value_verdict=None, fair_value_method=None, valuation_source=None)
    monkeypatch.setattr(dd, "get_active_valuation", lambda *a, **k: ret(pass_out))
    a = asyncio.run(dd.fair_value_block("ACME", no_value))
    monkeypatch.setattr(dd, "get_active_valuation", lambda *a, **k: ret(thin_out))
    b = asyncio.run(dd.fair_value_block("ACME", no_value))
    assert (a.available, a.unavailable_reason, a.unavailable_detail) == (False, "pass_method", "Losses and no P/B route")
    assert (b.available, b.unavailable_reason) == (False, "insufficient_data")


def test_fair_value_falls_back_to_the_cached_close_and_handles_no_summary(db):
    with Session(db) as session:
        session.add(TickerLastClose(ticker="ACME", close=95.0, as_of_date=date(2026, 10, 8), fetched_at=datetime.now()))
        session.commit()
    out = asyncio.run(dd.fair_value_block("ACME", summary(price=None)))
    assert out.price == 95.0 and out.discount_premium_pct == pytest.approx(-5.0)
    assert (asyncio.run(dd.fair_value_block("ACME", None))).unavailable_reason == "not_scored"


def test_fair_value_without_a_price_keeps_the_fair_value(db):
    out = asyncio.run(dd.fair_value_block("NOPRICE", summary(price=None)))
    assert out.available and out.price is None and out.unavailable_reason == "no_price" and out.discount_premium_pct is None


# --- Weinstein ---------------------------------------------------------------------------------------------------------------


def test_weinstein_series_is_the_production_engine_on_the_cached_bars(db):
    bars = daily_bars(1500, drift=0.002)  # steep enough to sit above the band
    with Session(db) as session:
        out = dd.weinstein_block(session, bars)
    prod = compute_weinstein_stage(bars, pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), WeinsteinParams())
    assert out.available and out.stage == prod.stage == "advance"
    assert out.since_date == prod.stage_since_date and out.since_is_lower_bound == prod.stage_since_is_lower_bound
    assert len(out.weeks) == 52 and out.weeks[-1].stage == "advance" and out.ma_label == "EMA30"
    assert all(a.week < b.week for a, b in zip(out.weeks, out.weeks[1:]))


def test_weinstein_follows_a_stage_switch_inside_the_year(db):
    up = daily_bars(900, drift=0.0010, end="2025-12-31")
    index = pd.bdate_range(start="2026-01-01", end="2026-10-09")
    close = up["close"].iloc[-1] * np.exp(-np.cumsum(np.full(len(index), 0.003)))
    down = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1e6}, index=index)
    with Session(db) as session:
        out = dd.weinstein_block(session, pd.concat([up, down]))
    stages = [w.stage for w in out.weeks]
    assert stages[0] == "advance" and stages[-1] == "decline" and out.stage == "decline"
    assert out.since_date is not None and not out.since_is_lower_bound


def test_weinstein_all_one_stage_reports_the_lower_bound(db):
    with Session(db) as session:
        out = dd.weinstein_block(session, daily_bars(300, drift=0.002))
    assert out.available and out.since_is_lower_bound


def test_weinstein_unavailable_under_the_minimum_weeks_or_without_bars(db):
    with Session(db) as session:
        thin = dd.weinstein_block(session, daily_bars(120))  # ~24 weeks
        none = dd.weinstein_block(session, None)
    assert not thin.available and thin.weeks == [] and thin.weeks_available < 40 and thin.weeks_required == 40
    assert "40 weeks" in thin.unavailable_reason
    assert not none.available and none.unavailable_reason == "No cached daily bars"


# --- the endpoint ------------------------------------------------------------------------------------------------------------


def test_endpoint_assembles_every_block_for_a_standard_stock(db, monkeypatch):
    seed_profile(db)
    with Session(db) as session:
        session.add(TickerScore(ticker="ACME", step1_score=70, step1_verdict="Pass", step2_score=60, step2_verdict="Fail", step4_score=75, step4_verdict="Pass", step5_score=88, step5_verdict="Pass", computed_at=datetime.now()))
        session.commit()
    patch_steps(monkeypatch, s1=step1(), s2=Step2Out(ticker="ACME", growth_rate=9.0, target_analyst_count=12, score=60, verdict="Fail", weights={}), s4=step4(), s5=step5_standard(), summ=summary())
    monkeypatch.setattr(dd, "read_cached_daily_bars_batch", lambda tickers, days, reference=None: {"ACME": daily_bars(1500)})
    body = get().json()
    assert body["applicable"] and body["has_data"] and body["company_type"] == "Standard"
    assert body["financials"]["stored_score"] == 70 and body["financials"]["score"] == 82
    assert body["growth"]["stored_verdict"] == "Fail" and body["growth"]["growth_rate"] == 9.0
    assert body["profitability"]["cutoffs"]["excellent"] == 15.0
    assert body["debt"]["ratios"][0]["pass_line"] == 1.0
    assert body["fair_value"]["band_low"] == 0.9 and body["moat"]["price_label"] == "5-year price"
    assert body["weinstein"]["available"] and len(body["weinstein"]["weeks"]) == 52


def test_endpoint_for_a_ticker_with_no_score_row_still_answers(db, monkeypatch):
    seed_profile(db)
    patch_steps(monkeypatch, s1=step1(), s2=Step2Out(ticker="ACME", verdict="insufficient_data", weights={}), s4=step4(), s5=step5_standard(), summ=summary())
    body = get().json()
    assert body["financials"]["stored_score"] is None and body["financials"]["stored_verdict"] is None
    assert body["growth"]["available"] is False and body["moat"]["rated"] is False
    assert body["weinstein"]["available"] is False and body["moat"]["price_series"] == []


def test_endpoint_survives_a_failing_step(db, monkeypatch):
    seed_profile(db)

    async def boom(*a, **k):
        raise RuntimeError("bad shape")

    patch_steps(monkeypatch, s1=step1(), s4=step4(), s5=step5_standard(), summ=summary())
    monkeypatch.setattr(dd, "get_step2_data", boom)
    body = get().json()
    assert body["growth"]["available"] is False and body["financials"]["available"] is True


def test_endpoint_etf_and_unknown_ticker(db, monkeypatch):
    patch_steps(monkeypatch)
    seed_profile(db, "SPY", isEtf=True)
    etf = get("SPY").json()
    assert etf["applicable"] is False and etf["not_applicable_reason"] == "Stocks only" and etf["has_data"] is False
    unknown = get("ZZZZ").json()
    assert unknown["applicable"] is True and unknown["has_data"] is False


@pytest.mark.parametrize(
    "company_type,exempt,roic,s5",
    [
        ("Bank", "Bank", False, Step5Out(ticker="ACME", company_type="Bank", ratios={"cet1_ratio": ratio(12.5), "npl_ratio": ratio(1.1)}, score=80, verdict="Pass", bank_capital_metrics_editable=True)),
        ("Insurance", "Insurance", False, Step5Out(ticker="ACME", company_type="Insurance", verdict="not_supported")),
        ("REIT/Property Developer", "Property Developer", False, Step5Out(ticker="ACME", company_type="REIT/Property Developer", ratios={"gearing_ratio": ratio(41.0, "approaching_limit", 70)}, score=70, verdict="Pass")),
        ("Utility", None, False, step5_standard(company_type="Utility")),
        ("Standard", None, True, step5_standard()),
    ],
)
def test_endpoint_company_type_variants(db, monkeypatch, company_type, exempt, roic, s5):
    seed_profile(db)
    patch_steps(monkeypatch, s1=step1(cfo_exempt_reason=exempt), s2=None, s4=step4(company_type=company_type, roic=roic), s5=s5, summ=summary())
    body = get().json()
    assert body["company_type"] == company_type
    assert body["financials"]["scored_cfo"] is (exempt is None)
    assert (body["profitability"]["roic"]["exempt_reason"] is None) is roic
    assert body["debt"]["status"] in {"scored", "not_applicable"}
    assert (body["debt"]["status"] == "not_applicable") is (company_type == "Insurance")


def test_the_endpoint_makes_no_fmp_call_and_writes_no_cache_row(db, monkeypatch):
    seed_profile(db)
    patch_steps(monkeypatch, s1=step1(), s4=step4(), s5=step5_standard(), summ=summary())
    with Session(db) as session:
        before = len(session.exec(select(FundamentalsCache)).all())
    assert get().status_code == 200
    with Session(db) as session:
        assert len(session.exec(select(FundamentalsCache)).all()) == before
