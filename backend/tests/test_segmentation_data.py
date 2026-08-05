import asyncio

from sqlmodel import SQLModel, create_engine

import data.segmentation_data as segmentation_data
from data.segmentation_data import MAX_SEGMENTS, OTHER_LABEL, _build_segment_series, get_segmentation_data

# Newest-first, matching FMP's actual payload ordering (confirmed empirically).
TWO_YEAR_ROWS = [
    {"fiscalYear": "2025", "date": "2025-09-27", "data": {"iPhone": 200.0, "Mac": 30.0, "Service": 100.0}},
    {"fiscalYear": "2024", "date": "2024-09-28", "data": {"iPhone": 190.0, "Mac": 28.0}},  # Service not broken out
]

EIGHT_SEGMENT_ROW = [
    {
        "fiscalYear": "2025",
        "date": "2025-09-27",
        "data": {f"Segment {i}": float(80 - i * 10) for i in range(8)},  # 80,70,...,10 -- 8 distinct segments
    }
]


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(segmentation_data, "engine", test_engine)


def test_ranks_segments_by_total_contribution_descending():
    years, segments, values = _build_segment_series(TWO_YEAR_ROWS)
    assert years == ["2024", "2025"]
    assert segments == ["iPhone", "Service", "Mac"]  # iPhone 390 > Service 100 > Mac 58


def test_missing_year_value_is_none_not_zero():
    _, _, values = _build_segment_series(TWO_YEAR_ROWS)
    # Service wasn't broken out in 2024 (oldest, index 0) -- must read as
    # None ("not disclosed that year"), never 0 ("no revenue").
    assert values["Service"] == [None, 100.0]


def test_empty_rows_returns_not_disclosed_shape():
    years, segments, values = _build_segment_series([])
    assert years == []
    assert segments is None
    assert values == {}


def test_folds_overflow_into_other_above_max_segments():
    assert MAX_SEGMENTS == 7
    years, segments, values = _build_segment_series(EIGHT_SEGMENT_ROW)
    assert len(segments) == MAX_SEGMENTS + 1
    assert segments[-1] == OTHER_LABEL
    # 8 segments valued 80..10 descending; top 7 kept (80..20), "Segment 7"
    # (value 10, the smallest) is the sole overflow into Other.
    assert values[OTHER_LABEL] == [10.0]


def test_seven_segments_exactly_at_cap_has_no_other_bucket():
    seven_segment_row = [
        {"fiscalYear": "2025", "date": "2025-09-27", "data": {f"Segment {i}": float(70 - i * 10) for i in range(7)}}
    ]
    _, segments, _ = _build_segment_series(seven_segment_row)
    assert len(segments) == 7
    assert OTHER_LABEL not in segments


def test_get_segmentation_data_maps_product_and_geographic(monkeypatch):
    _fresh_engine(monkeypatch)

    async def fake_product(ticker):
        return TWO_YEAR_ROWS

    async def fake_geographic(ticker):
        return []  # not disclosed for this ticker

    monkeypatch.setattr(segmentation_data.fmp_client, "get_revenue_product_segmentation", fake_product)
    monkeypatch.setattr(segmentation_data.fmp_client, "get_revenue_geographic_segmentation", fake_geographic)

    result = asyncio.run(get_segmentation_data("aapl"))

    assert result.ticker == "AAPL"
    assert result.product_years == ["2024", "2025"]
    assert result.product_segments == ["iPhone", "Service", "Mac"]
    assert result.geographic_years == []
    assert result.geographic_segments is None
