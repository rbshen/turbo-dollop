import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.ticker_score as ticker_score
from core.models import TechnicalEntrySignal, TickerScore, TrendAnalysis, WarrenSignalEvent
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
    quote_currency="USD",
    reported_currency=None,
    exchange="NASDAQ",
    is_etf=False,
    pe_ratio=30.0,
):
    return TickerSummaryOut(
        company_name=company_name,
        ticker="AAPL",
        sector=sector,
        industry=industry,
        exchange=exchange,
        is_etf=is_etf,
        market_cap=3_000_000_000_000.0,
        pe_ratio=pe_ratio,
        beta=1.2,
        fair_value_verdict=fair_value_verdict,
        valuation_source=valuation_source,
        perf_5y_vs_spy_pct=perf_5y_vs_spy_pct,
        perf_5y_vs_spy_status=perf_5y_vs_spy_status,
        quote_currency=quote_currency,
        reported_currency=reported_currency,
    )


def _speculative_growth(qualifies=True, company_type="Standard"):
    return SpeculativeGrowthOut(ticker="AAPL", qualifies=qualifies, company_type=company_type)


def _make_step(name, value, calls, raise_error=False):
    async def fn(ticker, cache_only=False, weights=None):
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
    # Steps score 90*0.30 + 80*0.20 + 70*0.20 + 60*0.30 = 75.0. No Moat rating is stored for AAPL here, so it is scored as No moat:
    # 75.0 x 0.70 = 52.5 -> 52 (half to even), a Fail; the multiplier and the unrounded Steps score are stored beside it.
    assert result.overall_score == 52
    assert result.overall_verdict == "Fail"
    assert (result.steps_score, result.moat_multiplier, result.moat) == (pytest.approx(75.0), 0.70, None)
    from scoring.overall import SCORE_FORMULA_VERSION

    assert result.formula_version == SCORE_FORMULA_VERSION
    assert result.market_cap == 3_000_000_000_000.0
    assert result.quote_currency == "USD"
    # Lifted verbatim from summary.pe_ratio (the trailing P/E, data/ticker_summary.py) -- no basis
    # logic of its own lives in this module.
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
    assert row.overall_score == 52
    assert row.speculative_growth_qualifies is True


def test_persist_false_computes_the_row_but_writes_nothing(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl", cache_only=True, persist=False))

    assert result is not None and result.step1_score == 90
    with Session(engine) as session:
        assert session.exec(select(TickerScore)).all() == []


def test_quote_currency_is_copied_from_summary_for_a_non_usd_ticker(monkeypatch):
    # 0700.HK-shaped: quote_currency flows straight through from
    # get_summary()'s own resolved value (see ticker_summary.py) -- no
    # separate FX/profile lookup in this module.
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, summary=_summary(quote_currency="HKD"))

    result = asyncio.run(compute_ticker_score("0700.HK"))

    assert result is not None
    assert result.quote_currency == "HKD"

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "0700.HK")).first()
    assert row is not None
    assert row.quote_currency == "HKD"


def test_reported_currency_is_copied_from_summary_for_a_non_usd_ticker(monkeypatch):
    # 0700.HK-shaped: reported_currency flows straight through from
    # get_summary()'s own resolved value -- backs the Watchlist's Revenue/
    # Net Income/CFO mini trend chart, which must always match the
    # Financials tab's own reported_currency for the same ticker (same
    # underlying annual-statement data).
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, summary=_summary(quote_currency="HKD", reported_currency="CNY"))

    result = asyncio.run(compute_ticker_score("0700.HK"))

    assert result is not None
    assert result.reported_currency == "CNY"

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "0700.HK")).first()
    assert row is not None
    assert row.reported_currency == "CNY"


def test_is_etf_is_persisted_true_for_an_etf_profile_and_false_for_a_stock(monkeypatch):
    # Lifted straight from summary.is_etf (FMP profile isEtf/isFund) -- a
    # pure field-mapping test, same shape as the other profile-lifted fields. The
    # ETF's company_type deliberately stays whatever step4/5 say ("ETF" in
    # real life) -- is_etf must not depend on it.
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, summary=_summary(company_name="State Street SPDR S&P 500 ETF", exchange="AMEX", is_etf=True))

    etf = asyncio.run(compute_ticker_score("SPY"))

    _patch_all(monkeypatch, summary=_summary(is_etf=False))
    stock = asyncio.run(compute_ticker_score("AAPL"))

    assert etf is not None and etf.is_etf is True
    assert stock is not None and stock.is_etf is False

    with Session(engine) as session:
        assert session.get(TickerScore, "SPY").is_etf is True
        assert session.get(TickerScore, "AAPL").is_etf is False


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
    assert result.overall_score == 52  # unaffected -- not an Overall Assessment input

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row.speculative_growth_qualifies is None


def test_weinstein_stage_is_copied_from_trend_analysis(monkeypatch):
    # Plain session.get(TrendAnalysis, ticker) read inside compute_ticker_score
    # -- not a live recomputation of the weekly engine. Same-session sibling
    # read as ticker_moat, so a pre-existing TrendAnalysis row is enough.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TrendAnalysis(
                ticker="AAPL",
                computed_at=datetime(2026, 9, 6),
                weinstein_stage="advance",
                weinstein_stage_since_date=date(2026, 1, 5),
                weinstein_stage_since_is_lower_bound=False,
                weinstein_ma_slope_pct=1.2,
                weinstein_vs_ma_pct=8.5,
                weinstein_pending_direction="decline",
            )
        )
        session.commit()
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.weinstein_stage == "advance"
    assert result.weinstein_stage_since_date == date(2026, 1, 5)
    assert result.weinstein_stage_since_is_lower_bound is False
    assert result.weinstein_ma_slope_pct == 1.2
    assert result.weinstein_vs_ma_pct == 8.5
    assert result.weinstein_pending_direction == "decline"

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row is not None
    assert row.weinstein_stage == "advance"
    assert row.weinstein_stage_since_date == date(2026, 1, 5)
    assert row.weinstein_stage_since_is_lower_bound is False
    assert row.weinstein_ma_slope_pct == 1.2
    assert row.weinstein_vs_ma_pct == 8.5
    assert row.weinstein_pending_direction == "decline"


def test_weinstein_stage_is_none_when_no_trend_analysis_row_exists(monkeypatch):
    # A ticker never touched by the Weinstein pipeline (or one whose
    # row predates this field -- see _add_missing_columns) reads as None,
    # same "no signal" contract as speculative_growth_qualifies above, and
    # never aborts the rest of the row.
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.weinstein_stage is None
    assert result.weinstein_stage_since_date is None
    assert result.weinstein_stage_since_is_lower_bound is None
    assert result.weinstein_ma_slope_pct is None
    assert result.weinstein_vs_ma_pct is None
    assert result.overall_score == 52  # unaffected -- not an Overall Assessment input

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row.weinstein_stage is None


def test_bb_rsi_entry_signal_is_true_for_a_recent_fire(monkeypatch):
    # Plain session.get(TechnicalEntrySignal, (ticker, "bb_rsi", "2h")) read
    # inside compute_ticker_score -- same same-session sibling-read pattern
    # as weinstein_stage/TrendAnalysis above. The stored value is DERIVED
    # (is_entry_signal_active on fired_at), not a raw stored flag -- there
    # is no such flag any more (see TechnicalEntrySignal.fired_at's own
    # comment).
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                fired_at=datetime.now() - timedelta(days=1),
                pct_b=0.02,
                rsi=24.1,
                close=210.5,
                source="fmp",
                as_of=datetime(2026, 9, 8, 15, 30),
                computed_at=datetime(2026, 9, 9, 3, 20),
            )
        )
        session.commit()
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.bb_rsi_entry_signal is True

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row.bb_rsi_entry_signal is True


def test_bb_rsi_entry_signal_is_false_for_a_fire_older_than_seven_days(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                fired_at=datetime.now() - timedelta(days=10),
                source="fmp",
                as_of=datetime(2026, 9, 8, 15, 30),
                computed_at=datetime(2026, 9, 9, 3, 20),
            )
        )
        session.commit()
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.bb_rsi_entry_signal is False


def test_bb_rsi_entry_signal_is_none_when_ticker_is_not_in_the_watchlist(monkeypatch):
    # A universe ticker on none of the W1-W5 named
    # watchlists (the overwhelming majority) has no TechnicalEntrySignal
    # row at all -- reads None, same "no signal" contract as speculative_growth_qualifies/
    # weinstein_stage above, never aborts the rest of the row.
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.bb_rsi_entry_signal is None
    assert result.overall_score == 52  # unaffected -- not an Overall Assessment input

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row.bb_rsi_entry_signal is None


def _warren_signal_row(signal_kind: str, **overrides) -> TechnicalEntrySignal:
    fields = dict(
        ticker="AAPL",
        signal_type="warren",
        timeframe="2h",
        signal_kind=signal_kind,
        fired_at=datetime(2026, 9, 8, 15, 30),
        source="fmp",
        as_of=datetime(2026, 9, 8, 15, 30),
        computed_at=datetime(2026, 9, 9, 3, 20),
    )
    fields.update(overrides)
    return TechnicalEntrySignal(**fields)


@pytest.mark.parametrize("signal_kind", ["blue_up", "yellow_up", "gray_up"])
def test_warren_active_signal_kind_is_copied_verbatim_for_every_up_kind(monkeypatch, signal_kind):
    # Plain session.get(TechnicalEntrySignal, (ticker, "warren", "2h")) read
    # inside compute_ticker_score -- same sibling-read pattern as
    # bb_rsi_entry_signal above, but DERIVED via warren_active_up_kind,
    # which treats all three Up-kinds symmetrically (see its own
    # docstring for why Gray Up is just as well-defined an "active" state
    # as Blue/Yellow Up).
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(_warren_signal_row(signal_kind))
        session.commit()
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.warren_active_signal_kind == signal_kind

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row.warren_active_signal_kind == signal_kind


@pytest.mark.parametrize("signal_kind", ["blue_down", "yellow_down", "gray_down"])
def test_warren_active_signal_kind_is_none_when_latest_kind_is_a_sell_arrow(monkeypatch, signal_kind):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(_warren_signal_row(signal_kind))
        session.commit()
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.warren_active_signal_kind is None


def test_warren_active_signal_kind_is_none_when_ticker_is_not_in_the_watchlist(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.warren_active_signal_kind is None
    assert result.warren_last_buy_fired_at is None
    assert result.overall_score == 52  # unaffected -- not an Overall Assessment input


def test_warren_last_buy_fired_at_is_max_across_up_kinds_regardless_of_active_state(monkeypatch):
    # Deliberately NOT read off TechnicalEntrySignal.fired_at -- the latest
    # recorded event here is a sell arrow (blue_down), so the snapshot's
    # own fired_at would misreport recency; warren_last_buy_fired_at must
    # instead reflect the true last BUY-side event from WarrenSignalEvent,
    # including gray_up -- and stays the same regardless of which kind(s)
    # the Screener's own filter is set to, since it's independent of
    # warren_active_signal_kind.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(_warren_signal_row("blue_down", fired_at=datetime(2026, 9, 10, 9, 30)))
        session.add_all(
            [
                WarrenSignalEvent(
                    ticker="AAPL", timeframe="2h", signal_kind="gray_up",
                    fired_at=datetime(2026, 9, 8, 15, 30), created_at=datetime(2026, 9, 8, 15, 30),
                ),
                WarrenSignalEvent(
                    ticker="AAPL", timeframe="2h", signal_kind="blue_down",
                    fired_at=datetime(2026, 9, 10, 9, 30), created_at=datetime(2026, 9, 10, 9, 30),
                ),
            ]
        )
        session.commit()
    _patch_all(monkeypatch)

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None
    assert result.warren_active_signal_kind is None
    assert result.warren_last_buy_fired_at == datetime(2026, 9, 8, 15, 30)


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
    assert result.overall_score == 52

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


def test_recompute_preserves_delisted_at(monkeypatch):
    """delisted_at is set by stale_data_health_check; a score recompute (which
    rewrites the whole row) must never clear it -- and must still update
    everything else."""
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch)
    flagged_at = datetime(2026, 9, 23, 21, 49)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL", delisted_at=flagged_at, overall_score=1, computed_at=datetime(2020, 1, 1)))
        session.commit()

    result = asyncio.run(compute_ticker_score("AAPL"))

    assert result is not None and result.overall_score == 52
    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).one()
    assert row.delisted_at == flagged_at
    assert row.overall_score == 52  # the rest of the row did update


def test_a_null_trailing_pe_is_stored_as_null(monkeypatch):
    # Loss-maker / ADR-without-a-usable-ratio: summary.pe_ratio is None and must land as NULL,
    # not 0 or a stale number.
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, summary=_summary(pe_ratio=None))

    result = asyncio.run(compute_ticker_score("aapl"))

    assert result is not None and result.pe_ratio is None
    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row is not None and row.pe_ratio is None


def test_a_recompute_overwrites_a_previously_stored_pe_with_null(monkeypatch):
    # The switch to the trailing basis turns some stored annual P/Es into NULL; the upsert must
    # write that NULL over the old value rather than keeping it (delisted_at is the only preserved column).
    engine = _fresh_engine(monkeypatch)
    _patch_all(monkeypatch, summary=_summary(pe_ratio=34.1))
    asyncio.run(compute_ticker_score("aapl"))
    _patch_all(monkeypatch, summary=_summary(pe_ratio=None))
    asyncio.run(compute_ticker_score("aapl"))

    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row is not None and row.pe_ratio is None


def test_an_etfs_stage_comes_from_its_trend_analysis_row_even_when_its_ticker_score_row_has_stopped_refreshing(monkeypatch):
    # ETF cutover 2026-10-03: nightly_score_recompute no longer touches ETFs, so an ETF's TickerScore row goes stale. The
    # Watchlist's compute_ticker_score(cache_only=True) re-derives the row live and copies the stage from TrendAnalysis,
    # which the nightly ETF job now writes -- so the stage is current without any recompute sweep.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL", computed_at=datetime(2026, 9, 29), is_etf=True, weinstein_stage="base"))
        session.add(TrendAnalysis(ticker="AAPL", computed_at=datetime(2026, 10, 3), weinstein_stage="advance"))
        session.commit()
    _patch_all(monkeypatch, summary=_summary())

    result = asyncio.run(compute_ticker_score("AAPL", cache_only=True))

    assert result.weinstein_stage == "advance"


# ---- Review status columns (scoring/review.py) -------------------------------------------------------------------


def _rate_moat(engine, moat="wide_moat"):
    from data.moat import set_ticker_moat

    with Session(engine) as session:
        set_ticker_moat(session, "AAPL", moat)


def _stored(engine) -> TickerScore:
    with Session(engine) as session:
        return session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).one()


def test_a_gated_step1_stores_the_review_columns_and_leaves_the_verdict_alone(monkeypatch):
    import json

    engine = _fresh_engine(monkeypatch)
    _rate_moat(engine)
    _patch_all(monkeypatch, step1=_step1(score=40, verdict="Fail"), step2=_step2(90), step4=_step4(90), step5=_step5(90))

    result = asyncio.run(compute_ticker_score("AAPL"))

    # Steps (40*30 + 90*20 + 90*20 + 90*30)/100 = 75.0 x Wide 1.0 -> 75, a passing score; Financials 40 is a weak step, so the label reads
    # "Pass with caution" (2026-10-08) and the Review status sits beside it, neither changing the other.
    assert result.overall_score == 75 and result.overall_verdict == "Pass with caution"
    assert result.review_status == "review_unclear"
    assert result.conviction == "high"
    row = _stored(engine)
    assert row.review_status == "review_unclear" and row.conviction == "high"
    reasons = json.loads(row.review_reasons)
    assert [(r["step"], r["score"], r["verdict"], r["hint"], r["rule"]) for r in reasons] == [("step1", 40, "Fail", "unclear", "step1_gated")]
    assert row.overall_verdict == result.overall_verdict and row.data_quality_flags is None

    from core.schemas import TickerScoreOut

    out = TickerScoreOut(**row.model_dump())
    assert out.review_status == "review_unclear" and out.review_reasons[0].step == "step1" and out.data_quality_flags is None


def test_every_score_computation_rewrites_the_review_columns_so_a_stale_status_never_lingers(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _rate_moat(engine)
    _patch_all(monkeypatch, step1=_step1(score=40, verdict="Fail"), step2=_step2(90), step4=_step4(90), step5=_step5(90))
    asyncio.run(compute_ticker_score("AAPL"))
    assert _stored(engine).review_status == "review_unclear"

    # Step 1 recovers (a Refresh, a recompute): status and reasons go back to None; conviction stays (Pass-family row).
    _patch_all(monkeypatch, step1=_step1(score=90), step2=_step2(90), step4=_step4(90), step5=_step5(90))
    asyncio.run(compute_ticker_score("AAPL"))
    row = _stored(engine)
    assert (row.review_status, row.review_reasons, row.conviction) == (None, None, "high")

    # The Moat is cleared (a Moat PUT): the ticker is scored as No moat (75 x 0.7 = 52, a Fail), so every review column is null.
    _patch_all(monkeypatch, step1=_step1(score=40, verdict="Fail"), step2=_step2(90), step4=_step4(90), step5=_step5(90))
    asyncio.run(compute_ticker_score("AAPL"))
    assert _stored(engine).review_status == "review_unclear"
    with Session(engine) as session:
        from core.models import TickerMoat

        session.delete(session.get(TickerMoat, "AAPL"))
        session.commit()
    asyncio.run(compute_ticker_score("AAPL"))
    row = _stored(engine)
    assert (row.overall_verdict, row.overall_score) == ("Fail", 52)
    assert (row.review_status, row.review_reasons, row.conviction) == (None, None, None)


def test_a_fail_row_never_gets_a_review_status(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _rate_moat(engine)
    _patch_all(monkeypatch, step1=_step1(score=10, verdict="Fail"), step2=_step2(10, "Fail"), step4=_step4(10, "Fail"), step5=_step5(10, "Fail"))
    result = asyncio.run(compute_ticker_score("AAPL"))
    assert result.overall_verdict == "Fail"
    assert (result.review_status, result.review_reasons, result.conviction) == (None, None, None)


def test_an_etf_gets_no_review_columns_and_reads_no_statements(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    def boom(*args, **kwargs):
        raise AssertionError("an ETF must not read statements for the review")

    monkeypatch.setattr(ticker_score, "read_cached_inputs", boom)
    _patch_all(monkeypatch, summary=_summary(is_etf=True))
    result = asyncio.run(compute_ticker_score("AAPL"))
    assert (result.review_status, result.review_reasons, result.conviction, result.data_quality_flags) == (None, None, None, None)


def test_a_skipped_upsert_after_a_failed_refresh_fetch_leaves_the_previous_review_untouched(monkeypatch):
    from core.cache import track_fetch_failures

    engine = _fresh_engine(monkeypatch)
    _rate_moat(engine)
    _patch_all(monkeypatch, step1=_step1(score=40, verdict="Fail"), step2=_step2(90), step4=_step4(90), step5=_step5(90))
    asyncio.run(compute_ticker_score("AAPL"))
    before = _stored(engine)

    _patch_all(monkeypatch, step1=_step1(score=90), step2=_step2(90), step4=_step4(90), step5=_step5(90))
    with track_fetch_failures() as tracker:
        tracker.unrecovered.append("income_statement/annual")
        asyncio.run(compute_ticker_score("AAPL"))
    after = _stored(engine)
    assert (after.review_status, after.review_reasons, after.conviction, after.step1_score) == (
        before.review_status,
        before.review_reasons,
        before.conviction,
        40,
    )


def test_a_review_failure_costs_the_row_nothing_but_its_own_columns(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _rate_moat(engine)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated")

    monkeypatch.setattr(ticker_score, "read_cached_inputs", boom)
    _patch_all(monkeypatch, step1=_step1(score=40, verdict="Fail"), step2=_step2(90), step4=_step4(90), step5=_step5(90))
    result = asyncio.run(compute_ticker_score("AAPL"))
    assert result.step1_score == 40 and result.overall_score is not None
    assert (result.review_status, result.review_reasons, result.conviction, result.data_quality_flags) == (None, None, None, None)


def test_the_data_quality_flags_are_stored_as_json_whether_or_not_there_is_a_status(monkeypatch):
    import json

    from core.schemas import DataQualityFlag

    engine = _fresh_engine(monkeypatch)
    flag = DataQualityFlag(rule="not_landed", statement="income", period="quarterly", period_end="2026-06-30", evidence="x")
    monkeypatch.setattr(ticker_score, "data_quality_flags", lambda raw, earnings, kind: [flag])
    _patch_all(monkeypatch)
    asyncio.run(compute_ticker_score("AAPL"))
    stored = json.loads(_stored(engine).data_quality_flags)
    assert [(f["rule"], f["period"], f["period_end"]) for f in stored] == [("not_landed", "quarterly", "2026-06-30")]


def test_the_review_reads_the_gate_constant_through_the_score_path(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _rate_moat(engine)
    _patch_all(monkeypatch, step1=_step1(score=60, verdict="Fail"), step2=_step2(90), step4=_step4(90), step5=_step5(90))
    assert asyncio.run(compute_ticker_score("AAPL", persist=False)).review_status is None
    monkeypatch.setattr(ticker_score, "REVIEW_GATE_SCORE", 70)
    assert asyncio.run(compute_ticker_score("AAPL", persist=False)).review_status == "review_unclear"
