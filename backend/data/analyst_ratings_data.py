import calendar
import logging
from datetime import date, datetime

import pandas as pd
from sqlmodel import Session, select

from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from helpers.first import _first
from clients.fmp_client import fmp_client
from clients.long_history_bars import get_long_history
from clients.yahoo_client import yahoo_client
from core.models import FundamentalsCache, PriceTargetSnapshot
from core.schemas import (
    AnalystRatingsOut,
    ConsensusBanner,
    PriceTargetRecencyBucket,
    PriceTargetSummary,
    RatingHistoryPoint,
    RecommendationDetailsColumn,
)
from core.tickers import normalize_ticker

# Weighted-score formula used to derive Mean/Consensus wherever FMP doesn't
# already hand us a consensus label -- see schemas.py's
# RecommendationDetailsColumn.consensus for why this only applies to the
# historical columns, never "Current".
RATING_WEIGHTS = {"strong_buy": 5, "buy": 4, "hold": 3, "sell": 2, "strong_sell": 1}
CONSENSUS_BANDS = [(4.5, "Buy"), (3.5, "Outperform"), (2.5, "Hold"), (1.5, "Underperform")]

# A snapshot (grades-historical row or PriceTargetSnapshot row) counts as
# "as of" a target date only if it falls within this many days of it --
# avoids a sparsely-covered ticker's stale/missing month silently reading as
# a much older or newer one.
SNAPSHOT_TOLERANCE_DAYS = 45

logger = logging.getLogger(__name__)

# Fetch period for the Price Target Trend chart's optional price overlay's YAHOO FALL-THROUGH
# (the FMP path reads the long-history store's own 10y window) --
# same value data/chart_data.py's own widest range (W_4Y) already uses,
# comfortably covering PriceTargetSnapshot's full backfilled history
# (2021-04 on, per CLAUDE.md) with room to spare, without introducing a new
# yfinance period tier of its own.
PRICE_OVERLAY_FETCH_PERIOD = "10y"


def _counts_from_grades_consensus(raw: dict) -> dict:
    return {
        "strong_buy": raw.get("strongBuy", 0) or 0,
        "buy": raw.get("buy", 0) or 0,
        "hold": raw.get("hold", 0) or 0,
        "sell": raw.get("sell", 0) or 0,
        "strong_sell": raw.get("strongSell", 0) or 0,
    }


def _counts_from_grades_historical_row(row: dict) -> dict:
    return {
        "strong_buy": row.get("analystRatingsStrongBuy", 0) or 0,
        "buy": row.get("analystRatingsBuy", 0) or 0,
        "hold": row.get("analystRatingsHold", 0) or 0,
        "sell": row.get("analystRatingsSell", 0) or 0,
        "strong_sell": row.get("analystRatingsStrongSell", 0) or 0,
    }


def _collapse_3bucket(counts: dict) -> tuple[int, int, int]:
    return counts["strong_buy"] + counts["buy"], counts["hold"], counts["sell"] + counts["strong_sell"]


def _weighted_score(counts: dict) -> float | None:
    total = sum(counts.values())
    if total == 0:
        return None
    return sum(RATING_WEIGHTS[key] * value for key, value in counts.items()) / total


def _band_consensus(score: float | None) -> str | None:
    if score is None:
        return None
    for threshold, label in CONSENSUS_BANDS:
        if score >= threshold:
            return label
    return "Sell"


def _months_ago(today: date, months: int) -> date:
    month_index = today.month - 1 - months
    year = today.year + month_index // 12
    month = month_index % 12 + 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _nearest_by_date(rows: list, target_date: date, date_key: str):
    """Closest row to target_date by `date_key` (a date object on SQLModel
    rows, an ISO date string on raw FMP dicts), or None if nothing falls
    within SNAPSHOT_TOLERANCE_DAYS."""
    best_row = None
    best_diff = None
    for row in rows:
        raw_date = row.get(date_key) if isinstance(row, dict) else getattr(row, date_key, None)
        if not raw_date:
            continue
        row_date = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
        diff = abs((row_date - target_date).days)
        if best_diff is None or diff < best_diff:
            best_diff, best_row = diff, row
    if best_row is None or best_diff > SNAPSHOT_TOLERANCE_DAYS:
        return None
    return best_row


async def _fetch_price_history(ticker: str) -> pd.Series:
    """Daily close series for the Price Target Trend chart's optional price overlay --
    date-indexed (tz-naive, normalized), ascending, empty (never raised) if no source has
    anything for this ticker.

    **Basis (FMP Phase 3, 2026-09-25): FMP `/historical-price-eod/full` closes -- split- (and
    spin-off-) adjusted, NOT dividend-adjusted.** Read from the ticker's on-demand long-history
    store (clients/long_history_bars.py: ~10y, its own table, filled on first view and topped up
    when stale; gated on `daily_prices_long` for a US listing, `daily_prices_intl` for a non-US
    one). Split-only is the right comparison for this chart: PriceTargetSnapshot's own
    reconstruction is built on FMP's split-adjusted `adjPriceTarget` (see helpers/
    price_target_history.py's docstring, and its GOOGL 2022-07 20:1-split example), and an
    analyst's nominal target is a statement about the price that actually traded -- a
    dividend-adjusted close deflates every earlier price by the dividends paid since, moving the
    price line away from the target line it is compared to (measured before this change: KO up to
    36% lower in 2016, SPY 17%, AAPL 9%). It also matches the Chart tab. **The visible change:
    for dividend payers the overlay's historical prices are now higher than the Yahoo `Adj Close`
    it used to show.** (Yahoo `Adj Close` was the pre-P3.7 basis; no path reads it any more.)
    Not routed through SharedBarsCache (nightly, ~5y, pruned).

    FALL-THROUGH (until Yahoo is removed in P6): when the group is off with no stored row, or FMP
    errors / answers empty, the Yahoo path runs, reading `Close` (split-only; auto_adjust=False is
    passed explicitly because yfinance's auto_adjust=True rescales `Close` for dividends) -- so the
    overlay has the same split-only basis whether FMP or Yahoo answers (P3.7b). If that has
    nothing either the overlay is simply empty."""
    try:
        daily = await get_long_history(ticker)
    except Exception as exc:  # noqa: BLE001 -- the overlay must never fail the tab; log the type only
        logger.warning("FMP long-history read failed for %s (%s); falling back to Yahoo", ticker, type(exc).__name__)
        daily = None
    if daily is not None and not daily.empty:
        series = daily["close"].dropna().astype(float)
        if not series.empty:
            series.index = pd.DatetimeIndex(series.index).normalize()
            return series.sort_index()

    result = await yahoo_client.get_history([ticker], period=PRICE_OVERLAY_FETCH_PERIOD, interval="1d", auto_adjust=False)
    frame = result.get(ticker)
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    series = frame["Close"].dropna()
    if series.empty:
        return series
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    series.index = index.normalize()
    return series.sort_index()


def _price_on_or_before(series: pd.Series, target: pd.Timestamp) -> float | None:
    """Last close at or before `target` -- the same "on or before" nearest-
    trading-day convention already used for this kind of date alignment
    elsewhere in this codebase (see scoring/etf_returns.py::
    _last_bar_on_or_before, scoring/momentum.py::_price_on_or_before).
    None if `series` has nothing that old yet (a young ticker, or a live
    fetch that simply doesn't reach back this far) -- never extrapolated
    or imputed."""
    eligible = series.loc[series.index <= target]
    if eligible.empty:
        return None
    return float(eligible.iloc[-1])


def _recency_buckets(raw: dict) -> list[PriceTargetRecencyBucket]:
    buckets = []
    for label, avg_key, count_key in (
        ("Last Month", "lastMonthAvgPriceTarget", "lastMonthCount"),
        ("Last Quarter", "lastQuarterAvgPriceTarget", "lastQuarterCount"),
        ("Last Year", "lastYearAvgPriceTarget", "lastYearCount"),
        ("All Time", "allTimeAvgPriceTarget", "allTimeCount"),
    ):
        count = raw.get(count_key, 0) or 0
        # FMP returns a literal 0 (not null) for the average when no analyst
        # issued a target within this window -- confirmed live (a quiet
        # ticker's lastMonthCount=0, lastMonthAvgPriceTarget=0). Without this
        # guard, a literal 0 reads downstream as a real $0.00 price target
        # rather than "no data for this period".
        avg = raw.get(avg_key) if count > 0 else None
        buckets.append(PriceTargetRecencyBucket(label=label, avg_price_target=avg, analyst_count=count))
    return buckets


def _details_column(label: str, counts: dict, mean: float | None, consensus: str | None, target: float | None) -> RecommendationDetailsColumn:
    # Row-label mapping is a 1:1 relabel of FMP's 5 buckets (strongBuy->Buy,
    # buy->Outperform, hold->Hold, sell->Underperform, strongSell->Sell),
    # not a collapse -- unlike ConsensusBanner's 3-bucket bar.
    return RecommendationDetailsColumn(
        label=label,
        buy=counts["strong_buy"],
        outperform=counts["buy"],
        hold=counts["hold"],
        underperform=counts["sell"],
        sell=counts["strong_sell"],
        mean=mean,
        consensus=consensus,
        target=target,
    )


async def get_analyst_ratings_data(ticker: str, cache_only: bool = False) -> AnalystRatingsOut:
    """`cache_only=True` reads only whatever's already cached and never
    calls FMP -- see cache.get_or_fetch's own cache_only branch, same
    convention as every other get_stepN_data function."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days
    today = date.today()

    with Session(engine) as session:
        grades_consensus_data = await safe_fetch(
            "grades_consensus",
            get_or_fetch(
                session, ticker, "grades_consensus", "latest", lambda: fmp_client.get_grades_consensus(ticker), staleness_days, cache_only
            ),
        )
        price_target_consensus_data = await safe_fetch(
            "price_target_consensus",
            get_or_fetch(
                session,
                ticker,
                "price_target_consensus",
                "latest",
                lambda: fmp_client.get_price_target_consensus(ticker),
                staleness_days,
                cache_only,
            ),
        )
        grades_historical_data = await safe_fetch(
            "grades_historical",
            get_or_fetch(
                session, ticker, "grades_historical", "latest", lambda: fmp_client.get_grades_historical(ticker), staleness_days, cache_only
            ),
        )
        price_target_summary_data = await safe_fetch(
            "price_target_summary",
            get_or_fetch(
                session,
                ticker,
                "price_target_summary",
                "latest",
                lambda: fmp_client.get_price_target_summary(ticker),
                staleness_days,
                cache_only,
            ),
        )
        # Reuses the "quote"/"latest" cache key ticker_summary.py and
        # step3_data.py already fetch under -- same data, no new key.
        quote_data = await safe_fetch(
            "quote", get_or_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker), staleness_days, cache_only)
        )
        snapshots = session.exec(
            select(PriceTargetSnapshot).where(PriceTargetSnapshot.ticker == ticker).order_by(PriceTargetSnapshot.snapshot_date)
        ).all()
        # fetched_at of the cached grades_consensus row -- surfaced so the UI
        # can caption "Current Distribution" as a live, independently-
        # refreshed FMP consensus snapshot, distinct from Recommendation
        # Trend's own grades_historical-sourced (monthly rating actions)
        # bars next to it. get_or_fetch itself only returns the raw
        # payload, not this metadata, so the row is re-read directly.
        grades_consensus_row = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == ticker,
                FundamentalsCache.statement_type == "grades_consensus",
                FundamentalsCache.period == "latest",
            )
        ).first()
        grades_consensus_as_of: datetime | None = grades_consensus_row.fetched_at if grades_consensus_row else None

    grades_consensus = _first(grades_consensus_data)
    price_target_consensus = _first(price_target_consensus_data)
    price_target_summary = _first(price_target_summary_data)
    quote = _first(quote_data)
    historical_rows = sorted(
        (row for row in (grades_historical_data if isinstance(grades_historical_data, list) else []) if row.get("date")),
        key=lambda row: row["date"],
    )

    current_counts = _counts_from_grades_consensus(grades_consensus)
    buy_count, hold_count, sell_count = _collapse_3bucket(current_counts)
    banner = ConsensusBanner(
        rating=grades_consensus.get("consensus") or "N/A",
        analyst_count=sum(current_counts.values()),
        buy_count=buy_count,
        hold_count=hold_count,
        sell_count=sell_count,
    )

    current_price = quote.get("price")
    target_consensus = price_target_consensus.get("targetConsensus")
    upside_pct = (target_consensus / current_price - 1) * 100 if current_price and target_consensus else None
    price_target = PriceTargetSummary(
        current_price=current_price,
        target_consensus=target_consensus,
        target_high=price_target_consensus.get("targetHigh"),
        target_low=price_target_consensus.get("targetLow"),
        target_median=price_target_consensus.get("targetMedian"),
        upside_pct=upside_pct,
    )

    history = []
    for row in historical_rows:
        counts = _counts_from_grades_historical_row(row)
        total = sum(counts.values())
        if total == 0:
            continue
        row_date = date.fromisoformat(row["date"][:10])
        snapshot = _nearest_by_date(snapshots, row_date, "snapshot_date")
        history.append(
            RatingHistoryPoint(
                date=row["date"][:10],
                # 1:1 relabel of FMP's 5 buckets, same mapping
                # _details_column uses for Current Distribution -- NOT
                # _collapse_3bucket's 3-bucket collapse, which would fold
                # Outperform/Underperform into Buy/Sell and understate the
                # real rating composition (see the RatingHistoryPoint
                # schema's own comment).
                buy_pct=counts["strong_buy"] / total * 100,
                outperform_pct=counts["buy"] / total * 100,
                hold_pct=counts["hold"] / total * 100,
                underperform_pct=counts["sell"] / total * 100,
                sell_pct=counts["strong_sell"] / total * 100,
                avg_rating=_weighted_score(counts),
                avg_price_target=snapshot.target_consensus if snapshot else None,
            )
        )

    # Price overlay (only attempted at all when there's a real price-target
    # line to overlay against -- and only ever populated from that line's
    # OWN first real point onward, never before it: see
    # RatingHistoryPoint.price_on_date's own comment for why a None run
    # right after that point, rather than a separate flag, is how "Yahoo's
    # history doesn't reach back this far" is represented). cache_only
    # skips this the same way it skips every other live external call in
    # this function -- Yahoo has no cache layer of its own here to fall
    # back to (see _fetch_price_history's own docstring), so cache_only
    # means "don't fetch" rather than "read the cache instead" -- and it must
    # not fetch INTO the long-history store either.
    target_start = next((i for i, point in enumerate(history) if point.avg_price_target is not None), None)
    if target_start is not None and not cache_only:
        price_series = await _fetch_price_history(ticker)
        if not price_series.empty:
            for point in history[target_start:]:
                point.price_on_date = _price_on_or_before(price_series, pd.Timestamp(point.date))

    columns = [
        _details_column(
            "Current", current_counts, _weighted_score(current_counts), grades_consensus.get("consensus"), target_consensus
        )
    ]
    for label, months in (("2M Ago", 2), ("6M Ago", 6), ("1Y Ago", 12)):
        target_date = _months_ago(today, months)
        hist_row = _nearest_by_date(historical_rows, target_date, "date")
        counts = _counts_from_grades_historical_row(hist_row) if hist_row else dict.fromkeys(RATING_WEIGHTS, 0)
        mean = _weighted_score(counts)
        snapshot = _nearest_by_date(snapshots, target_date, "snapshot_date")
        columns.append(_details_column(label, counts, mean, _band_consensus(mean), snapshot.target_consensus if snapshot else None))

    return AnalystRatingsOut(
        ticker=ticker,
        banner=banner,
        price_target=price_target,
        price_target_by_recency=_recency_buckets(price_target_summary),
        history=history,
        recommendation_details=columns,
        grades_consensus_as_of=grades_consensus_as_of,
    )
