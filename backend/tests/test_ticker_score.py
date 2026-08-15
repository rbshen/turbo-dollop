import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

import data.ticker_score as ticker_score
from core.models import TickerScore
from core.schemas import SpeculativeGrowthOut, Step1Out, Step2Out, Step4Out, Step5Out, TickerSummaryOut
from data.ticker_score import compute_ticker_score


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(ticker_score, "engine", engine)
    return engine


def _step1(score=90, verdict="Pass"):
    return Step1Out(
        ticker="AAPL",
        years=["TTM"],
        revenue=[1.0],
        net_income=[1.0],
        operating_income=[1.0],
        gross_margin=[1.0],
        net_margin=[1.0],
        score=score,
        verdict=verdict,
        components={},
        weights={},
    )


def _step2(score=80, verdict="Pass", growth_rate=12.5):
    return Step2Out(ticker="AAPL", score=score, verdict=verdict, growth_rate=growth_rate, components={}, weights={})


def _step4(score=70, verdict="Pass", company_type="Standard"):
    return Step4Out(
        ticker="AAPL",
        years=["TTM"],
        company_type=company_type,
        roe=[1.0],
        revenue=[1.0],
        accounts_receivable=[1.0],
        score=score,
        verdict=verdict,
    )


def _step5(score=60, verdict="Pass", company_type="Standard"):
    return Step5Out(ticker="AAPL", company_type=company_type, score=score, verdict=verdict)


def _summary(
    company_name="Apple Inc.",
    sector="Technology",
    industry="Consumer Electronics",
    fair_value_verdict="undervalued",
    valuation_source="auto",
    perf_5y_vs_spy_pct=None,
    perf_5y_vs_spy_status=None,
):
    return TickerSummaryOut(
        company_name=company_name,
        ticker="AAPL",
        sector=sector,
        industry=industry,
        market_cap=3_000_000_000_000.0,
        pe_ratio=30.0,
        beta=1.2,
        fair_value_verdict=fair_value_verdict,
        valuation_source=valuation_source,
        perf_5y_vs_spy_pct=perf_5y_vs_spy_pct,
        perf_5y_vs_spy_status=perf_5y_vs_spy_status,
    )


def _speculative_growth(qualifies=True, company_type="Standard"):
    return SpeculativeGrowthOut(ticker="AAPL", qualifies=qualifies, company_type=company_type)


def _make_step(name, value, calls, raise_error=False):
    async def fn(ticker, cache_only=False):
        calls.append((name, ticker, cache_only))
        if raise_error:
            raise RuntimeError(f"simulated failure in {name}")
        return value

    return fn


def _patch_all(
    monkeypatch,
    step1=None,
    step2=None,
    step4=None,
    step5=None,
    summary=None,
    speculative_growth=None,
    calls=None,
    error_steps=(),
):
    calls = calls if calls is not None else []

    monkeypatch.setattr(
        ticker_score, "get_step1_data", _make_step("step1", step1 or _step1(), calls, "step1" in error_steps)
    )
    monkeypatch.setattr(
        ticker_score, "get_step2_data", _make_step("step2", step2 or _step2(), calls, "step2" in error_steps)
    )
    monkeypatch.setattr(
        ticker_score, "get_step4_data", _make_step("step4", step4 or _step4(), calls, "step4" in error_steps)
    )
    monkeypatch.setattr(
        ticker_score, "get_step5_data", _make_step("step5", step5 or _step5(), calls, "step5" in error_steps)
    )
    monkeypatch.setattr(
        ticker_score, "get_summary", _make_step("summary", summary or _summary(), calls, "summary" in error_steps)
    )
    monkeypatch.setattr(
        ticker_score,
        "get_speculative_growth_data",
        _make_step(
            "speculative_growth",
            speculative_growth or _speculative_growth(),
            calls,
            "speculative_growth" in error_steps,
        ),
    )
    return calls


def test_computes_and_upserts_a_full_row(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.ticker == "AAPL"
    assert result.company_name == "Apple Inc."
    assert result.sector == "Technology"
    assert result.company_type == "Standard"
    assert result.step1_score == 90
    assert result.step2_score == 80
    assert result.step4_score == 70
    assert result.step5_score == 60
    # 90*(24/69) + 80*(10/69) + 70*(20/69) + 60*(15/69) = 5260/69 = 76.23 -> 76
    assert result.overall_score == 76
    assert result.overall_verdict == "Pass"
    assert result.market_cap == 3_000_000_000_000.0
    assert result.pe_ratio == 30.0
    assert result.beta == 1.2
    assert result.valuation_verdict == "undervalued"
    assert result.valuation_source == "auto"
    assert result.growth_rate == 12.5
    # _summary()'s defaults leave these unset -- confirms the fields are
    # wired through (None, not missing/erroring) even when get_summary has
    # nothing to report, same as every other optional field here.
    assert result.perf_5y_vs_spy_pct is None
    assert result.perf_5y_vs_spy_status is None
    # _speculative_growth()'s default (qualifies=True) is wired through.
    assert result.speculative_growth_qualifies is True

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row is not None
    assert row.overall_score == 76
    assert row.speculative_growth_qualifies is True


def test_perf_5y_vs_spy_fields_are_copied_from_summary(monkeypatch):
    # Lifted straight from the same get_summary() call market_cap/pe_ratio/
    # beta already come from (see ticker_score.py) -- no separate fetch of
    # its own, so this is a pure field-mapping test, same shape as
    # valuation_verdict/growth_rate above.
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, summary=_summary(perf_5y_vs_spy_pct=18.4, perf_5y_vs_spy_status="outperform"))

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.perf_5y_vs_spy_pct == 18.4
    assert result.perf_5y_vs_spy_status == "outperform"


def test_speculative_growth_qualifies_false_is_copied_through(monkeypatch):
    # Not just a truthy/falsy shortcut -- False must be preserved as False,
    # not coalesced to None the way a missing/errored step is below.
    _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, speculative_growth=_speculative_growth(qualifies=False, company_type="Bank"))

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.speculative_growth_qualifies is False


def test_speculative_growth_error_leaves_the_field_none_without_aborting_the_row(monkeypatch):
    # Same "one bad step doesn't kill the whole row" contract as Step 2's
    # own error case below -- and unlike step1/2/4/5, a speculative-growth
    # failure never touches overall_score/overall_verdict, since it isn't
    # one of compute_overall_assessment's inputs.
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, error_steps=("speculative_growth",))

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.speculative_growth_qualifies is None
    assert result.overall_score == 76  # unaffected -- not an Overall Assessment input

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row.speculative_growth_qualifies is None


def test_upsert_updates_an_existing_row_rather_than_erroring(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="AAPL",
                company_name="Old Name",
                overall_score=10,
                overall_verdict="Fail",
                computed_at=datetime(2020, 1, 1),
            )
        )
        session.commit()

    _patch_all(monkeypatch)
    result = asyncio.run(compute_ticker_score("AAPL"))

    assert result.company_name == "Apple Inc."
    assert result.overall_score == 76

    with Session(engine) as session:
        rows = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).all()
    assert len(rows) == 1  # updated in place, not duplicated
    assert rows[0].company_name == "Apple Inc."


def test_cache_only_is_passed_through_to_every_step_function(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_all(monkeypatch)

    asyncio.run(compute_ticker_score("AAPL", cache_only=True))

    assert len(calls) == 6
    assert all(cache_only is True for _, _, cache_only in calls)


def test_returns_none_when_no_cached_profile_exists(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, summary=_summary(company_name=None))

    result = asyncio.run(compute_ticker_score("ZZZZINVALID"))

    assert result is None


def test_a_single_erroring_step_does_not_abort_the_whole_row(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, error_steps=("step2",))

    result = asyncio.run(compute_ticker_score("AAPL"))

    assert result is not None  # the ticker still gets a row
    assert result.step2_score is None
    assert result.step2_verdict is None
    # Step 2 excluded from the overall calc (treated as incomplete/error) --
    # a confident overall score needs every step, so it's None here too.
    assert result.overall_score is None
    assert result.overall_verdict is None

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row.step1_score == 90  # the other 3 steps still computed fine
