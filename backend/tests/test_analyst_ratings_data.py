import asyncio
from datetime import date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

import data.analyst_ratings_data as analyst_ratings_data
from data.analyst_ratings_data import _months_ago, get_analyst_ratings_data
from core.models import PriceTargetSnapshot

TODAY = date.today()


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(analyst_ratings_data, "engine", test_engine)
    return test_engine


def _grades_historical_row(d: date, strong_buy=0, buy=0, hold=0, sell=0, strong_sell=0) -> dict:
    return {
        "date": d.isoformat(),
        "analystRatingsStrongBuy": strong_buy,
        "analystRatingsBuy": buy,
        "analystRatingsHold": hold,
        "analystRatingsSell": sell,
        "analystRatingsStrongSell": strong_sell,
    }


def _patch_fmp(
    monkeypatch,
    grades_consensus: dict,
    price_target_consensus: dict,
    grades_historical: list[dict],
    quote: dict,
):
    async def fake_grades_consensus(ticker):
        return [grades_consensus]

    async def fake_price_target_consensus(ticker):
        return [price_target_consensus]

    async def fake_grades_historical(ticker):
        return grades_historical

    async def fake_quote(ticker):
        return [quote]

    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_grades_consensus", fake_grades_consensus)
    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_price_target_consensus", fake_price_target_consensus)
    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_grades_historical", fake_grades_historical)
    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_quote", fake_quote)


def test_banner_collapses_five_buckets_to_three_and_uses_live_consensus_text(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 10, "buy": 20, "hold": 5, "sell": 2, "strongSell": 1, "consensus": "Strong Buy"},
        price_target_consensus={"targetConsensus": 150, "targetHigh": 200, "targetLow": 100, "targetMedian": 145},
        grades_historical=[],
        quote={"price": 100},
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert result.banner.rating == "Strong Buy"
    assert result.banner.analyst_count == 38
    assert result.banner.buy_count == 30  # strongBuy + buy
    assert result.banner.hold_count == 5
    assert result.banner.sell_count == 3  # sell + strongSell


def test_price_target_summary_computes_upside_and_handles_missing_price(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 1, "hold": 1, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 120, "targetHigh": 150, "targetLow": 90, "targetMedian": 118},
        grades_historical=[],
        quote={"price": 100},
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert result.price_target.target_consensus == 120
    assert result.price_target.upside_pct == pytest.approx(20.0)

    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 1, "hold": 1, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 120, "targetHigh": 150, "targetLow": 90, "targetMedian": 118},
        grades_historical=[],
        quote={},  # no price available
    )
    # Different ticker: get_or_fetch would otherwise serve the first call's
    # now-fresh "quote" cache row for TEST instead of re-invoking the fake.
    result = asyncio.run(get_analyst_ratings_data("TEST2"))
    assert result.price_target.current_price is None
    assert result.price_target.upside_pct is None


def test_current_column_uses_live_consensus_text_not_derived_banding(monkeypatch):
    _fresh_engine(monkeypatch)
    # A weighted score here would band to "Hold" (see CONSENSUS_BANDS), but
    # the Current column must show FMP's own live consensus text verbatim
    # instead -- this is the deliberate methodology difference documented
    # in schemas.py's RecommendationDetailsColumn.consensus.
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 0, "buy": 0, "hold": 10, "sell": 0, "strongSell": 0, "consensus": "Neutral"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[],
        quote={"price": 100},
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))
    current = result.recommendation_details[0]

    assert current.label == "Current"
    assert current.consensus == "Neutral"
    assert current.mean == pytest.approx(3.0)  # all-hold weighted score


def test_historical_columns_use_derived_weighted_mean_and_banding(monkeypatch):
    _fresh_engine(monkeypatch)
    two_months_ago = _months_ago(TODAY, 2)
    six_months_ago = _months_ago(TODAY, 6)
    one_year_ago = _months_ago(TODAY, 12)

    grades_historical = [
        _grades_historical_row(one_year_ago, strong_buy=0, buy=0, hold=0, sell=0, strong_sell=10),  # all strong sell -> 1.0
        _grades_historical_row(six_months_ago, strong_buy=0, buy=0, hold=10, sell=0, strong_sell=0),  # all hold -> 3.0
        _grades_historical_row(two_months_ago, strong_buy=10, buy=0, hold=0, sell=0, strong_sell=0),  # all strong buy -> 5.0
    ]
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=grades_historical,
        quote={"price": 100},
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))
    by_label = {col.label: col for col in result.recommendation_details}

    assert by_label["2M Ago"].mean == pytest.approx(5.0)
    assert by_label["2M Ago"].consensus == "Buy"
    assert by_label["2M Ago"].buy == 10  # strong_buy count lands in the "Buy" row per the row-label mapping

    assert by_label["6M Ago"].mean == pytest.approx(3.0)
    assert by_label["6M Ago"].consensus == "Hold"

    assert by_label["1Y Ago"].mean == pytest.approx(1.0)
    assert by_label["1Y Ago"].consensus == "Sell"


def test_historical_column_is_all_zero_and_null_consensus_when_no_snapshot_in_tolerance(monkeypatch):
    _fresh_engine(monkeypatch)
    # Only a snapshot from ~1 year ago exists -- nowhere near the 2M-ago
    # target within SNAPSHOT_TOLERANCE_DAYS, so that column must read as
    # "no data" rather than silently reusing a much older snapshot.
    grades_historical = [_grades_historical_row(_months_ago(TODAY, 12), strong_buy=5)]
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=grades_historical,
        quote={"price": 100},
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))
    by_label = {col.label: col for col in result.recommendation_details}

    assert by_label["2M Ago"].buy == 0
    assert by_label["2M Ago"].mean is None
    assert by_label["2M Ago"].consensus is None
    assert by_label["2M Ago"].target is None


def test_price_target_snapshot_populates_history_and_target_column_within_tolerance(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    two_months_ago = _months_ago(TODAY, 2)
    grades_historical = [_grades_historical_row(two_months_ago, strong_buy=1, buy=1, hold=1, sell=1, strong_sell=1)]
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 1, "hold": 1, "sell": 1, "strongSell": 1, "consensus": "Hold"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=grades_historical,
        quote={"price": 100},
    )

    with Session(test_engine) as session:
        session.add(
            PriceTargetSnapshot(
                ticker="TEST",
                snapshot_date=two_months_ago,
                target_consensus=88.0,
                target_high=100.0,
                target_low=70.0,
                target_median=85.0,
                fetched_at=datetime.now(),
            )
        )
        session.commit()

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert len(result.history) == 1
    assert result.history[0].avg_price_target == pytest.approx(88.0)

    by_label = {col.label: col for col in result.recommendation_details}
    assert by_label["2M Ago"].target == pytest.approx(88.0)
    # No snapshot near 6M/1Y ago -- must stay null, not fall back to the 2M one.
    assert by_label["6M Ago"].target is None
    assert by_label["1Y Ago"].target is None


def test_history_skips_all_zero_rows_and_returns_empty_when_no_historical_data(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "N/A"},
        price_target_consensus={},
        grades_historical=[_grades_historical_row(_months_ago(TODAY, 3))],  # all zero counts
        quote={},
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert result.history == []
    assert result.banner.analyst_count == 0
