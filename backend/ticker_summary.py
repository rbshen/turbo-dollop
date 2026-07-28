from datetime import date, timedelta

from sqlmodel import Session

from cache import force_fetch, get_or_fetch, safe_fetch
from config import settings
from db import engine
from debt_metrics import compute_debt_metrics
from first import _first
from fmp_client import fmp_client
from schemas import OutlierWarning, TickerSummaryOut
from shares import compute_shares_outstanding
from step2_data import get_step2_data
from step3_data import get_step3_data
from ttm import TOTAL_QUARTERS_NEEDED

# Trailing window for the daily price/volume fetch backing the 30-day
# average-volume and 20-day average-dollar-volume tiles -- comfortably
# covers both windows (30 calendar days and 20 trading days) plus weekends
# /holidays, without needing years of history: the 6 performance tiles are
# sourced from /stable/stock-price-change instead (see below), which already
# returns ytd/1Y/5Y/10Y pre-computed, so this fetch doesn't need to.
DAILY_PRICE_LOOKBACK_DAYS = 45

FAIR_VALUE_METHOD_LABELS = {
    "DCF": "DCF",
    "DFCF": "DFCF",
    "DNI": "DNI",
    "DNI_NORMALIZED": "DNI (Normalized)",
    "PRICE_TO_BOOK": "P/B",
    "PSG": "PSG",
}


def _next_earnings_date(earnings: list[dict]) -> date | None:
    """The nearest not-yet-reported (epsActual is null) earnings date --
    also requires the date itself to be in the future. ETFs (SPY, QQQ, ...)
    never report earnings, so every historical row FMP returns for them has
    a null epsActual; without the date check, `min()` over the entire
    history picks the OLDEST row in the dataset (a garbage decades-old
    "next earnings date") instead of correctly reading as "no earnings"."""
    today = date.today()
    upcoming = [
        row["date"]
        for row in earnings
        if row.get("date") and row.get("epsActual") is None and date.fromisoformat(row["date"][:10]) >= today
    ]
    if not upcoming:
        return None
    return date.fromisoformat(min(upcoming)[:10])


def _avg_volume_30d(daily_prices: list[dict]) -> float | None:
    """Average `volume` over the trailing 30 calendar days -- NOT
    profile.averageVolume, which was confirmed empirically to track closer
    to a ~50-63 trading-day average than a literal 30-day one."""
    if not daily_prices:
        return None
    most_recent = date.fromisoformat(daily_prices[0]["date"][:10])
    cutoff = most_recent - timedelta(days=30)
    window = [row for row in daily_prices if date.fromisoformat(row["date"][:10]) >= cutoff]
    if not window:
        return None
    return sum(row["volume"] for row in window) / len(window)


def _avg_dollar_volume_20d(daily_prices: list[dict]) -> float | None:
    """Average close*volume over the trailing 20 TRADING days (a distinct,
    independently-specified window from the 30-CALENDAR-day share-volume
    average above) -- FMP returns daily rows newest-first, confirmed
    empirically, so this is a plain positional slice."""
    window = daily_prices[:20]
    if not window:
        return None
    return sum(row["close"] * row["volume"] for row in window) / len(window)


async def get_summary(ticker: str, cache_only: bool = False) -> TickerSummaryOut:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch."""
    ticker = ticker.upper()
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
                ),
            )
        )
        # Price is fetched fresh on every live ticker-page view rather than
        # riding the fundamentals staleness window -- quote is its own cache
        # key, independent of profile/ratios/etc., so this doesn't force a
        # refetch of anything else bundled into this function. Skipped under
        # cache_only (the Screener recompute path), which must make zero FMP
        # calls (see recompute_ticker_scores.py).
        if cache_only:
            quote = _first(
                await safe_fetch(
                    "quote",
                    get_or_fetch(
                        session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker), staleness_days, cache_only
                    ),
                )
            )
        else:
            quote = _first(
                await safe_fetch(
                    "quote", force_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker))
                )
            )
        price_change = _first(
            await safe_fetch(
                "price_change",
                get_or_fetch(
                    session,
                    ticker,
                    "price_change",
                    "latest",
                    lambda: fmp_client.get_price_change(ticker),
                    staleness_days,
                    cache_only,
                ),
            )
        )
        ratios = _first(
            await safe_fetch(
                "ratios",
                get_or_fetch(
                    session, ticker, "ratios", "latest", lambda: fmp_client.get_ratios(ticker), staleness_days, cache_only
                ),
            )
        )
        earnings_data = await safe_fetch(
            "earnings",
            get_or_fetch(
                session, ticker, "earnings", "latest", lambda: fmp_client.get_earnings(ticker), staleness_days, cache_only
            ),
        )
        # Same cache key Step 4/Step 5/the Financials tab also populate
        # ("balance_sheet_statement"/"quarterly") -- limit is
        # TOTAL_QUARTERS_NEEDED to match them (bumped from 1 in the
        # Financials tab commit; this call site was missed then, and its
        # limit-1 fetch racing against theirs on a fresh ticker page load
        # would win and cache a thin 1-row result for everyone, since this
        # is the default tab and fetches first). This call site still only
        # reads row 0 below, so the deeper fetch doesn't change anything
        # here. compute_debt_metrics is the same shared calculation Step 5's
        # debt ratios use, so the header and Step 5's card can never show
        # inconsistent numbers for the same ticker.
        balance_sheet_data = await safe_fetch(
            "balance_sheet_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "balance_sheet_statement",
                "quarterly",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                cache_only,
            ),
        )
        income_quarterly_data = await safe_fetch(
            "income_statement_quarterly",
            get_or_fetch(
                session,
                ticker,
                "income_statement",
                "quarterly",
                lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                cache_only,
            ),
        )
        enterprise_values_data = await safe_fetch(
            "enterprise_values",
            get_or_fetch(
                session,
                ticker,
                "enterprise_values",
                "quarter",
                lambda: fmp_client.get_enterprise_values(ticker, "quarter", 1),
                staleness_days,
                cache_only,
            ),
        )
        # Same cache key ratios_data.py (the Ratios tab) already populates --
        # shared, not duplicated, so visiting either tab first warms it for
        # the other.
        ratios_ttm = _first(
            await safe_fetch(
                "ratios_ttm",
                get_or_fetch(
                    session, ticker, "ratios", "ttm", lambda: fmp_client.get_ratios_ttm(ticker), staleness_days, cache_only
                ),
            )
        )
        financial_growth = _first(
            await safe_fetch(
                "financial_growth",
                get_or_fetch(
                    session,
                    ticker,
                    "financial_growth",
                    "annual",
                    lambda: fmp_client.get_financial_growth(ticker, "annual", 1),
                    staleness_days,
                    cache_only,
                ),
            )
        )
        # ~45 calendar days is enough to cover both the 30-calendar-day
        # average-volume window and the 20-trading-day average-dollar-volume
        # window (see DAILY_PRICE_LOOKBACK_DAYS) -- the 6 performance tiles
        # come from price_change above instead, so this fetch doesn't need
        # years of history.
        today = date.today()
        daily_prices_data = await safe_fetch(
            "historical_price_eod",
            get_or_fetch(
                session,
                ticker,
                "historical_price_eod",
                "daily",
                lambda: fmp_client.get_historical_price_eod(
                    ticker, (today - timedelta(days=DAILY_PRICE_LOOKBACK_DAYS)).isoformat(), today.isoformat()
                ),
                staleness_days,
                cache_only,
            ),
        )

    earnings = earnings_data if isinstance(earnings_data, list) else []
    price = quote.get("price")
    income_quarterly = income_quarterly_data if isinstance(income_quarterly_data, list) else []
    debt_metrics = compute_debt_metrics(_first(balance_sheet_data), income_quarterly)
    enterprise_value = _first(enterprise_values_data).get("enterpriseValue")
    shares_outstanding, shares_outstanding_source = compute_shares_outstanding(quote, income_quarterly)
    daily_prices = daily_prices_data if isinstance(daily_prices_data, list) else []
    avg_volume_30d = _avg_volume_30d(daily_prices)
    avg_dollar_volume_20d = _avg_dollar_volume_20d(daily_prices)
    outlier_warnings = [
        OutlierWarning(metric=group.metric, date=fq.date, value=fq.value, trailing_median=fq.trailing_median)
        for group in debt_metrics.outlier_flags
        for fq in group.flagged
    ]

    # Step 2/Step 3 each manage their own Session(engine) block, separate
    # from this function's -- same non-conflicting pattern get_step3_data's
    # internal get_step2_data call already proves out.
    step2_out = await get_step2_data(ticker, cache_only)
    step3_out = await get_step3_data(ticker, cache_only)
    fair_value_method = (
        FAIR_VALUE_METHOD_LABELS.get(step3_out.selected_method) if step3_out.selected_method != "PASS" else None
    )

    return TickerSummaryOut(
        company_name=profile.get("companyName"),
        ticker=ticker,
        exchange=profile.get("exchangeShortName") or profile.get("exchange"),
        sector=profile.get("sector"),
        industry=profile.get("industry"),
        description=profile.get("description"),
        price=price,
        change=quote.get("change"),
        change_percent=quote.get("changePercentage", quote.get("changesPercentage")),
        market_cap=quote.get("marketCap") or profile.get("mktCap"),
        enterprise_value=enterprise_value,
        beta=profile.get("beta"),
        peg_ratio=ratios_ttm.get("priceToEarningsGrowthRatioTTM"),
        forward_peg_ratio=ratios_ttm.get("forwardPriceToEarningsGrowthRatioTTM"),
        dividend_yield=(
            ratios_ttm["dividendYieldTTM"] * 100 if ratios_ttm.get("dividendYieldTTM") is not None else None
        ),
        shares_outstanding=shares_outstanding,
        shares_outstanding_source=shares_outstanding_source,
        avg_volume_30d=avg_volume_30d,
        avg_dollar_volume_20d=avg_dollar_volume_20d,
        perf_1m=price_change.get("1M"),
        perf_6m=price_change.get("6M"),
        perf_ytd=price_change.get("ytd"),
        perf_1y=price_change.get("1Y"),
        perf_5y=price_change.get("5Y"),
        perf_10y=price_change.get("10Y"),
        week52_high=quote.get("yearHigh"),
        week52_low=quote.get("yearLow"),
        eps_growth_3_5y=step2_out.growth_rate,
        revenue_growth_yoy=(
            financial_growth["revenueGrowth"] * 100 if financial_growth.get("revenueGrowth") is not None else None
        ),
        net_income_growth_yoy=(
            financial_growth["netIncomeGrowth"] * 100 if financial_growth.get("netIncomeGrowth") is not None else None
        ),
        pe_ratio=ratios.get("priceToEarningsRatio"),
        next_earnings_date=_next_earnings_date(earnings),
        total_debt=debt_metrics.total_debt,
        ebitda_ttm=debt_metrics.ebitda_ttm,
        interest_expense_ttm=debt_metrics.interest_expense_ttm,
        interest_income_ttm=debt_metrics.interest_income_ttm,
        outlier_warnings=outlier_warnings,
        fair_value_price=step3_out.intrinsic_value_per_share,
        fair_value_verdict=step3_out.verdict,
        fair_value_method=fair_value_method,
    )
