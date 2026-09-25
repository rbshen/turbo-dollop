import asyncio
from datetime import date, datetime

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

import data.analyst_ratings_data as analyst_ratings_data
from data.analyst_ratings_data import _months_ago, _price_on_or_before, get_analyst_ratings_data
from core.models import PriceTargetSnapshot

TODAY = date.today()
_REAL_FETCH_PRICE_HISTORY = analyst_ratings_data._fetch_price_history  # captured before the autouse stub below


@pytest.fixture(autouse=True)
def _no_live_price_fetch(monkeypatch):
    """Every test in this file predates the price-overlay feature and has
    no expectations about it -- stub out the one genuinely live external
    call get_analyst_ratings_data can make (Yahoo Finance has no cache
    layer here to fall back to, see _fetch_price_history's own docstring)
    so these tests stay fast and network-free by default, mirroring
    test_chart_data.py's own `_default_no_warren_signal`-style autouse
    fixture for a similarly bolted-on dependency. Tests exercising the
    overlay itself override this."""

    async def _empty(_ticker):
        return pd.Series(dtype=float)

    monkeypatch.setattr(analyst_ratings_data, "_fetch_price_history", _empty)


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(analyst_ratings_data, "engine", test_engine)
    return test_engine


def _fail_if_called(_ticker):
    raise AssertionError("_fetch_price_history should not have been called")


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
    price_target_summary: dict | None = None,
):
    async def fake_grades_consensus(ticker):
        return [grades_consensus]

    async def fake_price_target_consensus(ticker):
        return [price_target_consensus]

    async def fake_grades_historical(ticker):
        return grades_historical

    async def fake_quote(ticker):
        return [quote]

    async def fake_price_target_summary(ticker):
        return [price_target_summary or {}]

    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_grades_consensus", fake_grades_consensus)
    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_price_target_consensus", fake_price_target_consensus)
    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_grades_historical", fake_grades_historical)
    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_quote", fake_quote)
    monkeypatch.setattr(analyst_ratings_data.fmp_client, "get_price_target_summary", fake_price_target_summary)


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


def test_price_target_by_recency_maps_all_four_fmp_buckets(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[],
        quote={"price": 100},
        price_target_summary={
            "lastMonthCount": 2,
            "lastMonthAvgPriceTarget": 352.0,
            "lastQuarterCount": 15,
            "lastQuarterAvgPriceTarget": 327.18,
            "lastYearCount": 67,
            "lastYearAvgPriceTarget": 312.65,
            "allTimeCount": 260,
            "allTimeAvgPriceTarget": 232.59,
        },
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))
    by_label = {b.label: b for b in result.price_target_by_recency}

    assert by_label["Last Month"].avg_price_target == pytest.approx(352.0)
    assert by_label["Last Month"].analyst_count == 2
    assert by_label["Last Quarter"].analyst_count == 15
    assert by_label["Last Year"].analyst_count == 67
    assert by_label["All Time"].avg_price_target == pytest.approx(232.59)
    assert by_label["All Time"].analyst_count == 260


def test_price_target_by_recency_treats_a_literal_zero_count_as_no_data(monkeypatch):
    # FMP returns a literal 0 (not null) for lastMonthAvgPriceTarget when
    # lastMonthCount is 0 -- a genuinely quiet period, distinct from a
    # missing/empty response (the other test below). Must read as "no data"
    # (avg_price_target=None), not a real $0.00 target.
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "N/A"},
        price_target_consensus={},
        grades_historical=[],
        quote={},
        price_target_summary={
            "lastMonthCount": 0,
            "lastMonthAvgPriceTarget": 0,
            "lastQuarterCount": 14,
            "lastQuarterAvgPriceTarget": 423.57,
            "lastYearCount": 102,
            "lastYearAvgPriceTarget": 368.37,
            "allTimeCount": 270,
            "allTimeAvgPriceTarget": 245.67,
        },
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))
    by_label = {b.label: b for b in result.price_target_by_recency}

    assert by_label["Last Month"].analyst_count == 0
    assert by_label["Last Month"].avg_price_target is None
    assert by_label["Last Quarter"].avg_price_target == pytest.approx(423.57)
    assert by_label["Last Quarter"].analyst_count == 14


def test_grades_consensus_as_of_reflects_the_cached_fetch_time(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[],
        quote={"price": 100},
    )

    before = datetime.now()
    result = asyncio.run(get_analyst_ratings_data("TEST"))
    after = datetime.now()

    assert result.grades_consensus_as_of is not None
    assert before <= result.grades_consensus_as_of <= after


def test_price_target_by_recency_defaults_when_fmp_returns_nothing(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "N/A"},
        price_target_consensus={},
        grades_historical=[],
        quote={},
        price_target_summary={},
    )

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert len(result.price_target_by_recency) == 4
    for bucket in result.price_target_by_recency:
        assert bucket.avg_price_target is None
        assert bucket.analyst_count == 0


def _price_series(pairs: list[tuple[date, float]]) -> pd.Series:
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in pairs])
    return pd.Series([v for _, v in pairs], index=idx).sort_index()


def test_price_on_or_before_finds_the_last_close_at_or_before_target_and_none_if_too_early():
    series = _price_series([(date(2024, 1, 2), 10.0), (date(2024, 1, 3), 11.0), (date(2024, 1, 5), 12.0)])

    # Exact match.
    assert _price_on_or_before(series, pd.Timestamp(2024, 1, 3)) == pytest.approx(11.0)
    # No bar on 1/4 (e.g. a weekend) -- falls back to the last real bar before it.
    assert _price_on_or_before(series, pd.Timestamp(2024, 1, 4)) == pytest.approx(11.0)
    # Nothing on or before this date at all.
    assert _price_on_or_before(series, pd.Timestamp(2024, 1, 1)) is None


def test_price_overlay_populates_from_the_targets_own_first_real_point_onward(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    three_months_ago = _months_ago(TODAY, 3)
    one_month_ago = _months_ago(TODAY, 1)
    grades_historical = [
        _grades_historical_row(three_months_ago, strong_buy=1),
        _grades_historical_row(one_month_ago, strong_buy=1),
    ]
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=grades_historical,
        quote={"price": 100},
    )
    with Session(test_engine) as session:
        session.add(
            PriceTargetSnapshot(
                ticker="TEST", snapshot_date=one_month_ago, target_consensus=88.0, target_high=100.0,
                target_low=70.0, target_median=85.0, fetched_at=datetime.now(),
            )
        )
        session.commit()

    # Real price data exists for the one row that has a real target
    # (one_month_ago) but not for the earlier row (three_months_ago) --
    # confirming the overlay never reaches back before the target series'
    # own first plotted point, and reads None (not extrapolated) where
    # Yahoo genuinely has no data.
    async def fake_prices(_ticker):
        return _price_series([(one_month_ago, 95.5)])

    monkeypatch.setattr(analyst_ratings_data, "_fetch_price_history", fake_prices)

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert len(result.history) == 2
    assert result.history[0].avg_price_target is None
    assert result.history[0].price_on_date is None  # never populated before the target line's own start
    assert result.history[1].avg_price_target == pytest.approx(88.0)
    assert result.history[1].price_on_date == pytest.approx(95.5)


def test_price_overlay_skipped_entirely_when_no_history_row_has_a_real_target(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[_grades_historical_row(_months_ago(TODAY, 2), strong_buy=1)],
        quote={"price": 100},
    )
    # No PriceTargetSnapshot at all -- avg_price_target stays None for every
    # row, so there's nothing to overlay against. _fetch_price_history must
    # never even be called.
    monkeypatch.setattr(analyst_ratings_data, "_fetch_price_history", _fail_if_called)

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert len(result.history) == 1
    assert result.history[0].avg_price_target is None
    assert result.history[0].price_on_date is None


def test_price_overlay_skipped_when_cache_only(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    two_months_ago = _months_ago(TODAY, 2)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[_grades_historical_row(two_months_ago, strong_buy=1)],
        quote={"price": 100},
    )
    with Session(test_engine) as session:
        session.add(
            PriceTargetSnapshot(
                ticker="TEST", snapshot_date=two_months_ago, target_consensus=88.0, target_high=100.0,
                target_low=70.0, target_median=85.0, fetched_at=datetime.now(),
            )
        )
        session.commit()

    # Warm the FundamentalsCache first (cache_only=True never calls FMP
    # either, so grades_historical/etc. must already be cached for this
    # ticker or the whole result comes back empty regardless of the price
    # overlay). Only then re-request with cache_only=True and confirm the
    # one genuinely live call left (Yahoo) still never fires.
    asyncio.run(get_analyst_ratings_data("TEST"))
    monkeypatch.setattr(analyst_ratings_data, "_fetch_price_history", _fail_if_called)

    result = asyncio.run(get_analyst_ratings_data("TEST", cache_only=True))

    assert result.history[0].avg_price_target == pytest.approx(88.0)
    assert result.history[0].price_on_date is None


def test_price_overlay_all_none_when_yahoo_has_zero_overlap_with_the_target_window(monkeypatch):
    """The real-world shape of "zero overlap" for a live, full-window Yahoo
    fetch: Yahoo returns data, but none of it falls on or before any of the
    target series' own plotted dates (e.g. a ticker Yahoo only recently
    picked up, or a symbol mismatch) -- every price_on_date must stay None,
    which is exactly what the frontend reads as "don't render the toggle"."""
    test_engine = _fresh_engine(monkeypatch)
    two_months_ago = _months_ago(TODAY, 2)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[_grades_historical_row(two_months_ago, strong_buy=1)],
        quote={"price": 100},
    )
    with Session(test_engine) as session:
        session.add(
            PriceTargetSnapshot(
                ticker="TEST", snapshot_date=two_months_ago, target_consensus=88.0, target_high=100.0,
                target_low=70.0, target_median=85.0, fetched_at=datetime.now(),
            )
        )
        session.commit()

    async def fake_prices(_ticker):
        # Only data from tomorrow onward -- strictly after the plotted row.
        return _price_series([(TODAY + pd.Timedelta(days=1), 50.0)])

    monkeypatch.setattr(analyst_ratings_data, "_fetch_price_history", fake_prices)

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert result.history[0].avg_price_target == pytest.approx(88.0)
    assert result.history[0].price_on_date is None


def test_price_overlay_handles_a_fully_empty_yahoo_response(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    two_months_ago = _months_ago(TODAY, 2)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[_grades_historical_row(two_months_ago, strong_buy=1)],
        quote={"price": 100},
    )
    with Session(test_engine) as session:
        session.add(
            PriceTargetSnapshot(
                ticker="TEST", snapshot_date=two_months_ago, target_consensus=88.0, target_high=100.0,
                target_low=70.0, target_median=85.0, fetched_at=datetime.now(),
            )
        )
        session.commit()

    async def empty_prices(_ticker):
        return pd.Series(dtype=float)

    monkeypatch.setattr(analyst_ratings_data, "_fetch_price_history", empty_prices)

    result = asyncio.run(get_analyst_ratings_data("TEST"))

    assert result.history[0].price_on_date is None


def test_overlay_end_to_end_reads_split_only_closes_from_the_long_history_store(monkeypatch):
    """get_analyst_ratings_data -> the real _fetch_price_history -> the FMP long-history store."""
    import clients.long_history_bars as lhb
    from core.models import LongHistoryBars

    test_engine = _fresh_engine(monkeypatch)
    one_month_ago = _months_ago(TODAY, 1)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[_grades_historical_row(one_month_ago, strong_buy=1)],
        quote={"price": 100},
    )
    with Session(test_engine) as session:
        session.add(PriceTargetSnapshot(ticker="TEST", snapshot_date=one_month_ago, target_consensus=88.0, target_high=100.0, target_low=70.0, target_median=85.0, fetched_at=datetime.now()))
        session.commit()
    with Session(lhb.engine) as session:
        session.add(LongHistoryBars(ticker="TEST", bar_time=datetime.combine(one_month_ago, datetime.min.time()), open=97.0, high=97.0, low=97.0, close=97.0, volume=1, fetched_at=datetime.now()))
        session.commit()
    monkeypatch.setattr(analyst_ratings_data, "_fetch_price_history", _REAL_FETCH_PRICE_HISTORY)

    result = asyncio.run(get_analyst_ratings_data("TEST"))
    assert result.history[0].price_on_date == pytest.approx(97.0)



def test_history_points_carry_the_matched_snapshots_methodology(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    old, recent = _months_ago(TODAY, 12), _months_ago(TODAY, 1)
    _patch_fmp(
        monkeypatch,
        grades_consensus={"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0, "consensus": "Buy"},
        price_target_consensus={"targetConsensus": 100, "targetHigh": 100, "targetLow": 100, "targetMedian": 100},
        grades_historical=[_grades_historical_row(old, strong_buy=1), _grades_historical_row(recent, strong_buy=1), _grades_historical_row(_months_ago(TODAY, 6), strong_buy=1)],
        quote={"price": 100},
    )
    with Session(test_engine) as session:
        session.add(PriceTargetSnapshot(ticker="TEST", snapshot_date=old, target_consensus=50.0, fetched_at=datetime.now(), methodology="legacy_all_analysts"))
        session.add(PriceTargetSnapshot(ticker="TEST", snapshot_date=recent, target_consensus=80.0, fetched_at=datetime.now(), methodology="live_consensus"))
        session.commit()

    result = asyncio.run(get_analyst_ratings_data("TEST"))
    by_target = {p.avg_price_target: p.methodology for p in result.history}
    assert by_target[50.0] == "legacy_all_analysts"
    assert by_target[80.0] == "live_consensus"
    assert by_target[None] is None  # no snapshot near the 6M point -> no methodology either
