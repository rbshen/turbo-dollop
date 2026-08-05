from sqlmodel import Session

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from fmp_client import fmp_client
from schemas import SegmentationOut

# Same 10yr consistency convention as Step 1/Step 4/Ratios (see CLAUDE.md) --
# annual-only on our FMP plan (period=quarter 402s on both segmentation
# endpoints, confirmed empirically), so there's no TTM column to extend to.
ANNUAL_WINDOW = 10

# Validated against real payloads: GOOGL and AMZN both report exactly 7
# segments in their latest fiscal year, so this cap absorbs real cases
# directly -- only busier breakdowns fold the remainder into "Other".
MAX_SEGMENTS = 7
OTHER_LABEL = "Other"


def _annual_year(row: dict) -> str:
    return str(row.get("fiscalYear") or row.get("date", "")[:4])


def _build_segment_series(
    rows: list[dict], window: int = ANNUAL_WINDOW, max_segments: int = MAX_SEGMENTS
) -> tuple[list[str], list[str] | None, dict[str, list[float | None]]]:
    """Builds (years, segment_names, values) from FMP's revenue-segmentation
    rows (newest-first, each a {..., "data": {segment_name: revenue}} dict).
    Segments are ranked by total $ contribution across the window
    (descending) so the most prominent segment always lands in the same
    chart slot; only the top `max_segments` are kept individually, the rest
    are summed per-year into an "Other" bucket (added only if non-empty).
    A segment not broken out in a given year is None there, never 0 -- 0
    would misreport "not disclosed that year" as "no revenue"."""
    if not rows:
        return [], None, {}

    windowed = list(reversed(rows[:window]))  # oldest-first, matches every other chart in the app
    years = [_annual_year(row) for row in windowed]

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
        values[OTHER_LABEL] = other_values
        segments.append(OTHER_LABEL)

    return years, segments, values


async def get_segmentation_data(ticker: str, cache_only: bool = False) -> SegmentationOut:
    """`cache_only=True` reads only whatever's already cached and never calls
    FMP -- same convention as get_step1_data/get_ratios_data."""
    ticker = ticker.upper()
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        product_data = await safe_fetch(
            "revenue_product_segmentation",
            get_or_fetch(
                session,
                ticker,
                "revenue_product_segmentation",
                "annual",
                lambda: fmp_client.get_revenue_product_segmentation(ticker),
                staleness_days,
                cache_only,
            ),
        )
        geographic_data = await safe_fetch(
            "revenue_geographic_segmentation",
            get_or_fetch(
                session,
                ticker,
                "revenue_geographic_segmentation",
                "annual",
                lambda: fmp_client.get_revenue_geographic_segmentation(ticker),
                staleness_days,
                cache_only,
            ),
        )

    product_rows = product_data if isinstance(product_data, list) else []
    geographic_rows = geographic_data if isinstance(geographic_data, list) else []

    product_years, product_segments, product_values = _build_segment_series(product_rows)
    geographic_years, geographic_segments, geographic_values = _build_segment_series(geographic_rows)

    return SegmentationOut(
        ticker=ticker,
        product_years=product_years,
        product_segments=product_segments,
        product_values=product_values,
        geographic_years=geographic_years,
        geographic_segments=geographic_segments,
        geographic_values=geographic_values,
    )
