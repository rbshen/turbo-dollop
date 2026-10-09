import asyncio

import pytest

from sqlmodel import SQLModel, create_engine

import data.segmentation_data as segmentation_data
from data.segmentation_data import (
    MAX_SEGMENTS,
    OTHER_LABEL,
    _build_segment_series,
    _detect_likely_totals,
    get_segmentation_data,
)

# Newest-first, matching FMP's actual payload ordering (confirmed empirically).
TWO_YEAR_ROWS = [
    {"fiscalYear": "2025", "date": "2025-09-27", "data": {"iPhone": 200.0, "Mac": 30.0, "Service": 100.0}},
    {"fiscalYear": "2024", "date": "2024-09-28", "data": {"iPhone": 190.0, "Mac": 28.0}},  # Service not broken out
]

# Shaped like MCO's real cached data: revenue serialized as a JSON string, not a
# number -- confirmed live for MCO/NOC's product segmentation (see CLAUDE.md).
STRING_VALUED_ROWS = [
    {"fiscalYear": "2024", "date": "2024-12-31", "data": {"Moodys Analytics": 3400000000.0, "Moodys Investors Service": 2950000000.0}},
    {"fiscalYear": "2023", "date": "2023-12-31", "data": {"Moodys Analytics": "3056000000", "Moodys Investors Service": "2860000000"}},
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


def test_string_valued_revenue_is_coerced_to_float_not_raising():
    years, segments, values = _build_segment_series(STRING_VALUED_ROWS)
    assert years == ["2023", "2024"]
    # Both segments' totals must be real numbers (crashed with a TypeError
    # before the fix, mixing a string 2023 value with a float 2024 value).
    assert values["Moodys Analytics"] == [3056000000.0, 3400000000.0]
    assert values["Moodys Investors Service"] == [2860000000.0, 2950000000.0]
    assert all(isinstance(v, float) for series in values.values() for v in series)


def test_unparseable_string_revenue_reads_as_none_not_zero():
    rows = [
        {"fiscalYear": "2024", "date": "2024-12-31", "data": {"Segment A": 50.0, "Segment B": 120.0}},
        {"fiscalYear": "2023", "date": "2023-12-31", "data": {"Segment A": "N/A", "Segment B": 100.0}},
    ]
    _, _, values = _build_segment_series(rows)
    # Segment A's unparseable 2023 value reads as None ("not disclosed"), never 0
    # ("no revenue") -- same convention as a genuinely missing value.
    assert values["Segment A"] == [None, 50.0]
    assert values["Segment B"] == [100.0, 120.0]


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


def _other_rows(other_name: str) -> list[dict]:
    # Newest-first. Six large segments plus the provider's own "Other" fill the
    # seven kept slots; Tiny A / Tiny B rank below and overflow.
    big = {f"Big {i}": float(1000 - i * 100) for i in range(6)}
    return [
        {"fiscalYear": "2025", "date": "2025-12-31", "data": {**big, other_name: 300.0, "Tiny A": 5.0, "Tiny B": 2.0}},
        {"fiscalYear": "2024", "date": "2024-12-31", "data": {**big, other_name: 280.0, "Tiny A": 4.0}},
        {"fiscalYear": "2023", "date": "2023-12-31", "data": {**big, "Tiny B": 3.0}},  # overflow only
        {"fiscalYear": "2022", "date": "2022-12-31", "data": {**big, other_name: 250.0}},  # real Other only
        {"fiscalYear": "2021", "date": "2021-12-31", "data": dict(big)},  # neither
    ]


EXPECTED_MERGED_OTHER = [None, 250.0, 3.0, 284.0, 307.0]  # 2021..2025


def test_real_other_in_top_segments_absorbs_overflow_into_single_series():
    years, segments, values = _build_segment_series(_other_rows("Other"))
    assert years == ["2021", "2022", "2023", "2024", "2025"]
    assert segments.count("Other") == 1
    assert len(segments) == len(set(segments)) == MAX_SEGMENTS
    assert values["Other"] == EXPECTED_MERGED_OTHER


def test_no_real_other_keeps_synthetic_bucket_unchanged():
    _, segments, values = _build_segment_series(EIGHT_SEGMENT_ROW)
    assert segments.count(OTHER_LABEL) == 1
    assert segments[-1] == OTHER_LABEL
    assert len(segments) == MAX_SEGMENTS + 1
    assert values[OTHER_LABEL] == [10.0]


@pytest.mark.parametrize("name", ["Others", " other ", "OTHER"])
def test_other_name_variants_merge_and_keep_provider_label(name):
    _, segments, values = _build_segment_series(_other_rows(name))
    assert len(segments) == len(set(segments)) == MAX_SEGMENTS
    assert name in segments
    assert OTHER_LABEL not in segments
    assert values[name] == EXPECTED_MERGED_OTHER


def _flags(rows):
    return {item.segment: item.years for item in _detect_likely_totals(rows)}


# MEDP-like (newest-first): "Revenue Net" equals the sum of the parts in 2023 and
# 2022 only; elsewhere it is a small unrelated figure or absent.
MEDP_LIKE_ROWS = [
    {"fiscalYear": "2025", "date": "2025-12-31", "data": {"Oncology": 700.0, "Metabolic": 600.0, "Cardiology": 200.0, "Other": 400.0}},
    {
        "fiscalYear": "2023",
        "date": "2023-12-31",
        "data": {"Oncology": 600.0, "Metabolic": 400.0, "Cardiology": 200.0, "Other": 400.0, "Revenue Net": 1600.0},
    },
    {
        "fiscalYear": "2022",
        "date": "2022-12-31",
        "data": {"Oncology": 500.0, "Metabolic": 300.0, "Cardiology": 150.0, "Other": 300.0, "Revenue Net": 1250.0},
    },
    {
        "fiscalYear": "2021",
        "date": "2021-12-31",
        "data": {"Oncology": 360.0, "Metabolic": 160.0, "Cardiology": 120.0, "Other": 270.0, "Revenue Net": 34.5},
    },
]


def test_likely_total_flagged_only_in_years_it_equals_the_sum():
    assert _flags(MEDP_LIKE_ROWS) == {"Revenue Net": ["2022", "2023"]}


def test_detection_does_not_change_built_series():
    before = _build_segment_series(MEDP_LIKE_ROWS)
    _detect_likely_totals(MEDP_LIKE_ROWS)
    assert _build_segment_series(MEDP_LIKE_ROWS) == before
    assert "Revenue Net" in before[1]  # still drawn as a segment; warning only


def test_normal_ticker_is_not_flagged():
    assert _detect_likely_totals(TWO_YEAR_ROWS) == []
    assert _detect_likely_totals(EIGHT_SEGMENT_ROW) == []
    assert _detect_likely_totals([]) == []


def test_two_other_segments_need_a_total_looking_name():
    named = [{"fiscalYear": "2024", "date": "2024-12-31", "data": {"A": 60.0, "B": 40.0, "Total Revenue": 100.0}}]
    plain = [{"fiscalYear": "2024", "date": "2024-12-31", "data": {"A": 60.0, "B": 40.0, "Domains": 100.0}}]
    assert _flags(named) == {"Total Revenue": ["2024"]}
    assert _flags(plain) == {}


def test_three_other_segments_flag_any_name():
    rows = [{"fiscalYear": "2024", "date": "2024-12-31", "data": {"A": 10.0, "B": 20.0, "C": 30.0, "Sum Line": 60.0}}]
    assert _flags(rows) == {"Sum Line": ["2024"]}


def test_two_segment_split_is_never_flagged():
    # Only one other segment: a "Total" beside a single part is not evidence of anything.
    rows = [{"fiscalYear": "2024", "date": "2024-12-31", "data": {"US": 50.0, "Total Foreign Operations": 50.0}}]
    assert _flags(rows) == {}


def test_gddy_style_near_coincidence_is_not_flagged():
    # GoDaddy 2021 (millions): Domains is within ~1% of the other two, but it is a
    # real segment -- outside the 0.25% tolerance and only two others.
    rows = [
        {
            "fiscalYear": "2021",
            "date": "2021-12-31",
            "data": {"Business Applications": 489.5, "Domains": 1323.2, "Hosting and Presence": 820.7},
        }
    ]
    assert _flags(rows) == {}
    # Even an exact match with a non-total name and only two others stays unflagged.
    exact = [{"fiscalYear": "2021", "date": "2021-12-31", "data": {"A": 489.5, "Domains": 1310.2, "B": 820.7}}]
    assert _flags(exact) == {}


def _gap_row(year: str, name: str, gap: float) -> dict:
    # Three parts summing to 600; `name` is 600 * (1 + gap) -- a gap of 0.001 is 0.1%.
    return {
        "fiscalYear": year,
        "date": f"{year}-12-31",
        "data": {"A": 100.0, "B": 200.0, "C": 300.0, name: 600.0 * (1 + gap)},
    }


def test_plain_name_one_year_at_point_one_percent_is_not_flagged():
    assert _flags([_gap_row("2024", "Domains", 0.001)]) == {}


def test_plain_name_one_exact_year_is_flagged():
    assert _flags([_gap_row("2024", "Domains", 0.0)]) == {"Domains": ["2024"]}
    assert _flags([_gap_row("2024", "Domains", 0.0001)]) == {"Domains": ["2024"]}  # exact-tie boundary (0.01%)
    assert _flags([_gap_row("2024", "Domains", 0.00011)]) == {}


def test_plain_name_two_years_at_point_two_percent_is_flagged():
    rows = [_gap_row("2024", "Domains", 0.002), _gap_row("2023", "Domains", -0.002)]
    assert _flags(rows) == {"Domains": ["2023", "2024"]}


def test_plain_name_reports_only_years_inside_tolerance():
    rows = [_gap_row("2024", "Domains", 0.002), _gap_row("2023", "Domains", 0.002), _gap_row("2022", "Domains", 0.004)]
    assert _flags(rows) == {"Domains": ["2023", "2024"]}


def test_total_looking_name_one_year_at_point_two_percent_is_flagged():
    assert _flags([_gap_row("2024", "Revenue Net", 0.002)]) == {"Revenue Net": ["2024"]}
    assert _flags([_gap_row("2024", "Segment Total", 0.002)]) == {"Segment Total": ["2024"]}


def test_gap_of_point_three_percent_is_never_flagged():
    for name in ("Domains", "Revenue Net"):
        assert _flags([_gap_row("2024", name, 0.003)]) == {}
        assert _flags([_gap_row("2024", name, 0.003), _gap_row("2023", name, 0.003)]) == {}
    # A 0.3% year does not count toward the two-year requirement either.
    assert _flags([_gap_row("2024", "Domains", 0.002), _gap_row("2023", "Domains", 0.003)]) == {}


def test_single_year_near_miss_beside_an_exact_year_reports_only_passing_years():
    rows = [_gap_row("2024", "Domains", 0.0), _gap_row("2023", "Domains", 0.003)]
    assert _flags(rows) == {"Domains": ["2024"]}


def test_get_segmentation_data_exposes_likely_totals(monkeypatch):
    _fresh_engine(monkeypatch)

    async def fake_product(ticker):
        return MEDP_LIKE_ROWS

    async def fake_geographic(ticker):
        return []

    monkeypatch.setattr(segmentation_data.fmp_client, "get_revenue_product_segmentation", fake_product)
    monkeypatch.setattr(segmentation_data.fmp_client, "get_revenue_geographic_segmentation", fake_geographic)

    result = asyncio.run(get_segmentation_data("medp"))

    assert [(x.segment, x.years) for x in result.product_likely_totals] == [("Revenue Net", ["2022", "2023"])]
    assert result.geographic_likely_totals == []
    assert "Revenue Net" in result.product_segments


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
