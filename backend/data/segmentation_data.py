import logging
import re

from sqlmodel import Session

from core.cache import get_or_fetch_earnings_aware, safe_fetch
from core.config import settings
from core.db import engine
from clients.fmp_client import fmp_client
from core.schemas import LikelyTotal, SegmentationOut
from core.tickers import normalize_ticker
from helpers.earnings import resolve_most_recent_earnings_date

# Same 10yr consistency convention as Step 1/Step 4/Ratios (see CLAUDE.md) --
# annual-only on our FMP plan (period=quarter 402s on both segmentation
# endpoints, confirmed empirically), so there's no TTM column to extend to.
ANNUAL_WINDOW = 10

logger = logging.getLogger(__name__)

# Validated against real payloads: GOOGL and AMZN both report exactly 7
# segments in their latest fiscal year, so this cap absorbs real cases
# directly -- only busier breakdowns fold the remainder into "Other".
MAX_SEGMENTS = 7
OTHER_LABEL = "Other"
_OTHER_NAMES = {"other", "others"}


def _is_other_name(name: str) -> bool:
    return name.strip().lower() in _OTHER_NAMES


# Likely-total detection (warning only -- no value is ever altered). A segment
# matches in a year when it equals the sum of every other positive segment that
# year within TOTAL_TOLERANCE and at least MIN_OTHERS_PLAIN other positive
# segments exist, or MIN_OTHERS_TOTAL_NAMED when its name also reads like a
# total. A total-looking name is flagged on one matching year; a plain name
# needs MIN_YEARS_PLAIN matching years or one EXACT_TIE_TOLERANCE tie (a single
# near-miss is usually just a segment that is about half of sales). FMP
# sometimes returns a consolidated/"Revenue Net" line beside its parts (MEDP
# 2022-2023), which a stacked chart then counts twice.
TOTAL_TOLERANCE = 0.0025
EXACT_TIE_TOLERANCE = 0.0001
MIN_OTHERS_PLAIN = 3
MIN_OTHERS_TOTAL_NAMED = 2
MIN_YEARS_PLAIN = 2
_TOTAL_NAME = re.compile(r"total|revenue|consolidated", re.IGNORECASE)


def _annual_year(row: dict) -> str:
    return str(row.get("fiscalYear") or row.get("date", "")[:4])


def _coerce_numeric(value: object) -> float | None:
    """FMP's segmentation endpoints sometimes serialize a segment's revenue as a
    JSON string rather than a number (confirmed live: MCO/NOC's product
    segmentation, several years each) -- inconsistently, even within the same
    ticker's own series. int/float/numeric-string coerce to float; anything else
    (None, an unparseable string) reads as "not disclosed" (None), same as a
    genuinely missing value -- never fabricated as 0."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _build_segment_series(
    rows: list[dict], window: int = ANNUAL_WINDOW, max_segments: int = MAX_SEGMENTS
) -> tuple[list[str], list[str] | None, dict[str, list[float | None]]]:
    """Builds (years, segment_names, values) from FMP's revenue-segmentation
    rows (newest-first, each a {..., "data": {segment_name: revenue}} dict).
    Segments are ranked by total $ contribution across the window
    (descending) so the most prominent segment always lands in the same
    chart slot; only the top `max_segments` are kept individually, the rest
    are summed per-year into an "Other" bucket (added only if non-empty). If a
    kept segment is already an "Other"-type name the provider itself reports
    (case/whitespace-insensitive: "Other", "Others", " other "), the overflow
    is added into that series, under the provider's label, rather than
    creating a second "Other" series that would collide on the chart key.
    A segment not broken out in a given year is None there, never 0 -- 0
    would misreport "not disclosed that year" as "no revenue"."""
    if not rows:
        return [], None, {}

    windowed = list(reversed(rows[:window]))  # oldest-first, matches every other chart in the app
    years = [_annual_year(row) for row in windowed]
    windowed = [
        {**row, "data": {name: _coerce_numeric(value) for name, value in (row.get("data") or {}).items()}}
        for row in windowed
    ]

    totals: dict[str, float] = {}
    for row in windowed:
        for name, value in (row.get("data") or {}).items():
            if value is not None:
                totals[name] = totals.get(name, 0.0) + value

    ranked = sorted(totals, key=lambda name: totals[name], reverse=True)
    kept = ranked[:max_segments]
    overflow = ranked[max_segments:]

    values: dict[str, list[float | None]] = {name: [] for name in kept}
    other_values: list[float | None] = []
    for row in windowed:
        data = row.get("data") or {}
        for name in kept:
            values[name].append(data.get(name))
        if overflow:
            overflow_values = [data.get(name) for name in overflow if data.get(name) is not None]
            other_values.append(sum(overflow_values) if overflow_values else None)

    segments = list(kept)
    if overflow:
        existing_other = next((name for name in kept if _is_other_name(name)), None)
        if existing_other is not None:
            # None only when neither the provider's own value nor the overflow has one.
            values[existing_other] = [
                None if real is None and extra is None else (real or 0.0) + (extra or 0.0)
                for real, extra in zip(values[existing_other], other_values)
            ]
        else:
            values[OTHER_LABEL] = other_values
            segments.append(OTHER_LABEL)

    return years, segments, values


def _detect_likely_totals(rows: list[dict], window: int = ANNUAL_WINDOW) -> list[LikelyTotal]:
    """Per-year check on the raw values, before MAX_SEGMENTS ranking and the
    "Other" rollup. Returns one entry per flagged segment with its flagged
    fiscal years (oldest-first); [] when nothing looks like a total."""
    if not rows:
        return []

    matches: dict[str, list[tuple[str, float]]] = {}  # name -> [(fiscal year, gap)], oldest-first
    for row in reversed(rows[:window]):  # oldest-first
        data = {name: _coerce_numeric(value) for name, value in (row.get("data") or {}).items()}
        positive = {name: value for name, value in data.items() if value is not None and value > 0}
        total_of_all = sum(positive.values())
        for name, value in positive.items():
            others_count = len(positive) - 1
            others_sum = total_of_all - value
            min_others = MIN_OTHERS_TOTAL_NAMED if _TOTAL_NAME.search(name) else MIN_OTHERS_PLAIN
            if others_count < min_others or others_sum <= 0:
                continue
            gap = abs(value - others_sum) / others_sum
            if gap <= TOTAL_TOLERANCE:
                matches.setdefault(name, []).append((_annual_year(row), gap))

    flagged: list[LikelyTotal] = []
    for name, hits in matches.items():
        looks_like_total = bool(_TOTAL_NAME.search(name))
        years = [year for year, _ in hits]
        has_exact_tie = any(gap <= EXACT_TIE_TOLERANCE for _, gap in hits)
        if looks_like_total or len(set(years)) >= MIN_YEARS_PLAIN or has_exact_tie:
            flagged.append(LikelyTotal(segment=name, years=years))
    return flagged


def _log_likely_totals(ticker: str, kind: str, likely: list[LikelyTotal]) -> None:
    for item in likely:
        logger.info("segmentation likely total: %s %s %r in FY %s", ticker, kind, item.segment, ", ".join(item.years))


async def get_segmentation_data(ticker: str, cache_only: bool = False) -> SegmentationOut:
    """`cache_only=True` reads only whatever's already cached and never calls
    FMP -- same convention as get_step1_data/get_ratios_data."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        most_recent_earnings_date = await resolve_most_recent_earnings_date(session, ticker, staleness_days, cache_only)
        product_data = await safe_fetch(
            "revenue_product_segmentation",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "revenue_product_segmentation",
                "annual",
                lambda: fmp_client.get_revenue_product_segmentation(ticker),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        geographic_data = await safe_fetch(
            "revenue_geographic_segmentation",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "revenue_geographic_segmentation",
                "annual",
                lambda: fmp_client.get_revenue_geographic_segmentation(ticker),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )

    product_rows = product_data if isinstance(product_data, list) else []
    geographic_rows = geographic_data if isinstance(geographic_data, list) else []

    product_years, product_segments, product_values = _build_segment_series(product_rows)
    geographic_years, geographic_segments, geographic_values = _build_segment_series(geographic_rows)

    product_likely_totals = _detect_likely_totals(product_rows)
    geographic_likely_totals = _detect_likely_totals(geographic_rows)
    _log_likely_totals(ticker, "product", product_likely_totals)
    _log_likely_totals(ticker, "geographic", geographic_likely_totals)

    return SegmentationOut(
        ticker=ticker,
        product_years=product_years,
        product_segments=product_segments,
        product_values=product_values,
        geographic_years=geographic_years,
        geographic_segments=geographic_segments,
        geographic_values=geographic_values,
        product_likely_totals=product_likely_totals,
        geographic_likely_totals=geographic_likely_totals,
    )
