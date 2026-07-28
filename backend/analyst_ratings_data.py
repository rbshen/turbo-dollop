import calendar
from datetime import date

from sqlmodel import Session, select

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from first import _first
from fmp_client import fmp_client
from models import PriceTargetSnapshot
from schemas import AnalystRatingsOut, ConsensusBanner, PriceTargetSummary, RatingHistoryPoint, RecommendationDetailsColumn

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
    ticker = ticker.upper()
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
        # Reuses the "quote"/"latest" cache key ticker_summary.py and
        # step3_data.py already fetch under -- same data, no new key.
        quote_data = await safe_fetch(
            "quote", get_or_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker), staleness_days, cache_only)
        )
        snapshots = session.exec(
            select(PriceTargetSnapshot).where(PriceTargetSnapshot.ticker == ticker).order_by(PriceTargetSnapshot.snapshot_date)
        ).all()

    grades_consensus = _first(grades_consensus_data)
    price_target_consensus = _first(price_target_consensus_data)
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
        buy, hold, sell = _collapse_3bucket(counts)
        row_date = date.fromisoformat(row["date"][:10])
        snapshot = _nearest_by_date(snapshots, row_date, "snapshot_date")
        history.append(
            RatingHistoryPoint(
                date=row["date"][:10],
                buy_pct=buy / total * 100,
                hold_pct=hold / total * 100,
                sell_pct=sell / total * 100,
                avg_rating=_weighted_score(counts),
                avg_price_target=snapshot.target_consensus if snapshot else None,
            )
        )

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
        ticker=ticker, banner=banner, price_target=price_target, history=history, recommendation_details=columns
    )
