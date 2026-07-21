import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

import ticker_score
from models import TickerScore
from schemas import Step1Out, Step2Out, Step4Out, Step5Out, TickerSummaryOut
from ticker_score import compute_ticker_score


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
    )


def _step2(score=80, verdict="Pass"):
    return Step2Out(ticker="AAPL", score=score, verdict=verdict, components={})


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


def _summary(company_name="Apple Inc.", sector="Technology", industry="Consumer Electronics"):
    return TickerSummaryOut(
        company_name=company_name,
        ticker="AAPL",
        sector=sector,
        industry=industry,
        market_cap=3_000_000_000_000.0,
        pe_ratio=30.0,
        beta=1.2,
    )


def _make_step(name, value, calls, raise_error=False):
    async def fn(ticker, cache_only=False):
        calls.append((name, ticker, cache_only))
        if raise_error:
            raise RuntimeError(f"simulated failure in {name}")
        return value

    return fn


def _patch_all(monkeypatch, step1=None, step2=None, step4=None, step5=None, summary=None, calls=None, error_steps=()):
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
    # 90*0.35 + 80*0.22 + 70*0.28 + 60*0.15 = 77.7 -> 78
    assert result.overall_score == 78
    assert result.overall_verdict == "Pass"
    assert result.market_cap == 3_000_000_000_000.0
    assert result.pe_ratio == 30.0
    assert result.beta == 1.2

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row is not None
    assert row.overall_score == 78


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
    assert result.overall_score == 78

    with Session(engine) as session:
        rows = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).all()
    assert len(rows) == 1  # updated in place, not duplicated
    assert rows[0].company_name == "Apple Inc."


def test_cache_only_is_passed_through_to_every_step_function(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_all(monkeypatch)

    asyncio.run(compute_ticker_score("AAPL", cache_only=True))

    assert len(calls) == 5
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
