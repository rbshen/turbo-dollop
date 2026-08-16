import logging
from datetime import date, timedelta

import httpx
from sqlmodel import Session

from core.cache import force_fetch, get_or_fetch, get_or_fetch_earnings_aware, safe_fetch
from core.config import settings
from core.db import engine
from core.exceptions import TickerNotFoundError
from helpers.debt_metrics import compute_debt_metrics
from helpers.earnings import most_recent_reported_earnings_date
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.schemas import OutlierWarning, TickerSummaryOut
from core.tickers import normalize_ticker
from helpers.shares import compute_shares_outstanding, is_implausible_magnitude_shift
from data.step2_data import get_step2_data
from data.step3_data import get_active_valuation
from helpers.ttm import TOTAL_QUARTERS_NEEDED

logger = logging.getLogger(__name__)

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


def _resolve_perf_vs_spy(
    ticker: str, price_change: dict, spy_price_change: dict
) -> tuple[float | None, str | None, bool]:
    """Returns (perf_5y_vs_spy_pct, status, insufficient_history).

    status is None (pill/number hidden entirely) only for SPY's own page --
    "SPY vs SPY" isn't a meaningful comparison. Otherwise status is
    "outperform" / "underperform" / "match" (pct exactly 0.0, a literal tie,
    not a rounding band) / "no_data" -- "no_data" only when the spread
    genuinely can't be computed (this ticker's own "5Y" figure is missing --
    e.g. safe_fetch swallowed a fetch error to `{}`), never merely because
    the ticker has under 5 years of trading history -- see
    insufficient_history below, which still gets a real outperform/
    underperform/match read, just flagged for a caveat.

    insufficient_history detects FMP's confirmed (live-tested) behavior of
    silently clamping 3Y/5Y/10Y/max to the same value when a ticker's actual
    trading history is shorter than the window -- e.g. a ticker IPO'd 18
    months ago reports "5Y": <return since listing>, identical to its own
    "10Y"/"max". Comparing against `max` catches the common case (5Y clamped
    straight to lifetime return); comparing against `10Y` catches the same
    clamp when `max` happens to differ slightly (e.g. after a restatement)."""
    if ticker == "SPY":
        return None, None, False
    ticker_5y = price_change.get("5Y")
    spy_5y = spy_price_change.get("5Y")
    if ticker_5y is None or spy_5y is None:
        return None, "no_data", False
    insufficient_history = ticker_5y == price_change.get("max") or ticker_5y == price_change.get("10Y")
    pct = ticker_5y - spy_5y
    if pct > 0:
        status = "outperform"
    elif pct < 0:
        status = "underperform"
    else:
        status = "match"
    return pct, status, insufficient_history


async def get_summary(ticker: str, cache_only: bool = False) -> TickerSummaryOut:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days

    with Session(engine) as session:
        if cache_only:
            profile = _first(
                await safe_fetch(
                    "profile",
                    get_or_fetch(
                        session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
                    ),
                )
            )
        else:
            # Deliberately the very first fetch in this function, and
            # deliberately NOT routed through the usual safe_fetch(...) one-
            # liner: a genuine 200-with-empty-list ("this ticker doesn't
            # exist") and a transient httpx.HTTPError ("FMP is down right
            # now") need different outcomes, not the same {} fallback --
            # see CLAUDE.md's ticker-search UX investigation. An empty
            # result raises TickerNotFoundError (main.py turns this into a
            # 404). A real fetch failure degrades to {} exactly like
            # safe_fetch always has -- this endpoint has never 502'd on a
            # transient FMP outage (see
            # test_refresh.py::test_fmp_failure_right_after_refresh_degrades_gracefully_not_a_crash)
            # and a bad ticker vs. an unreachable FMP must not be
            # conflated in the other direction either: an outage must never
            # display as "ticker not found". Checking this before any of
            # the other ~10 FMP calls below (and before
            # get_step2_data/get_active_valuation, which make several more
            # of their own) means a genuinely bad ticker short-circuits
            # here instead of paying for the full cascade just to end up
            # blank anyway.
            try:
                profile_raw = await get_or_fetch(
                    session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
                )
            except httpx.HTTPError as exc:
                logger.warning("FMP fetch failed for profile: %s", exc)
                profile_raw = {}
            else:
                if isinstance(profile_raw, list) and not profile_raw:
                    raise TickerNotFoundError(ticker)
            profile = _first(profile_raw)
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
        # SPY's own 5Y return, for the "vs SPY" performance pill/metric below.
        # Same cache key shape as `price_change` above, just under ticker="SPY"
        # -- fetched/cached once and reused by every other ticker's request
        # (get_or_fetch's cache key is (ticker, category, period), so this
        # naturally namespaces to its own row). Reuse price_change directly
        # when ticker IS "SPY", rather than issuing a second, redundant fetch
        # for the identical cache row.
        spy_price_change = (
            price_change
            if ticker == "SPY"
            else _first(
                await safe_fetch(
                    "price_change_spy",
                    get_or_fetch(
                        session, "SPY", "price_change", "latest", lambda: fmp_client.get_price_change("SPY"), staleness_days, cache_only
                    ),
                )
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
        # Reduced from the same /earnings fetch above, not a second fetch --
        # get_summary already needs this data for next_earnings_date below.
        most_recent_earnings_date = most_recent_reported_earnings_date(
            earnings_data if isinstance(earnings_data, list) else []
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
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "balance_sheet_statement",
                "quarterly",
                lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
                cache_only,
            ),
        )
        income_quarterly_data = await safe_fetch(
            "income_statement_quarterly",
            get_or_fetch_earnings_aware(
                session,
                ticker,
                "income_statement",
                "quarterly",
                lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
                staleness_days,
                most_recent_earnings_date,
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
                get_or_fetch_earnings_aware(
                    session,
                    ticker,
                    "ratios",
                    "ttm",
                    lambda: fmp_client.get_ratios_ttm(ticker),
                    staleness_days,
                    most_recent_earnings_date,
                    cache_only,
                ),
            )
        )
        financial_growth = _first(
            await safe_fetch(
                "financial_growth",
                get_or_fetch_earnings_aware(
                    session,
                    ticker,
                    "financial_growth",
                    "annual",
                    lambda: fmp_client.get_financial_growth(ticker, "annual", 1),
                    staleness_days,
                    most_recent_earnings_date,
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
    shares_outstanding, shares_outstanding_source = compute_shares_outstanding(quote, income_quarterly)
    enterprise_values_row = _first(enterprise_values_data)
    # Guards against FMP's freshly-filed-quarter units defect (confirmed:
    # TEAM, FLY -- enterprise_values.numberOfShares off by ~1000x on the
    # latest quarter, dragging marketCapitalization/enterpriseValue down by
    # the same factor). shares_outstanding is already the reliable figure
    # (compute_shares_outstanding prefers quote.marketCap/price), so it's
    # reused here as the reference rather than fetching anything new.
    enterprise_value = (
        None
        if is_implausible_magnitude_shift(enterprise_values_row.get("numberOfShares"), shares_outstanding)
        else enterprise_values_row.get("enterpriseValue")
    )
    daily_prices = daily_prices_data if isinstance(daily_prices_data, list) else []
    avg_volume_30d = _avg_volume_30d(daily_prices)
    avg_dollar_volume_20d = _avg_dollar_volume_20d(daily_prices)
    outlier_warnings = [
        OutlierWarning(metric=group.metric, date=fq.date, value=fq.value, trailing_median=fq.trailing_median)
        for group in debt_metrics.outlier_flags
        for fq in group.flagged
    ]
    perf_5y_vs_spy_pct, perf_5y_vs_spy_status, perf_5y_insufficient_history = _resolve_perf_vs_spy(
        ticker, price_change, spy_price_change
    )

    # Step 2/Step 3 each manage their own Session(engine) block, separate
    # from this function's. step2_out is passed into get_active_valuation
    # (rather than left for it to fetch on its own) since this function
    # already needs it directly for eps_growth_3_5y below -- computing it
    # twice (cache read + full Step 2 scoring) in one /summary request was
    # pure redundant work, not a correctness issue. get_active_valuation
    # (not get_step3_data directly) so the header's FairValuePill reflects
    # an active custom valuation the same way the Valuation tab does.
    step2_out = await get_step2_data(ticker, cache_only)
    step3_out = await get_active_valuation(ticker, cache_only, step2_out=step2_out)
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
        perf_5y_vs_spy_pct=perf_5y_vs_spy_pct,
        perf_5y_vs_spy_status=perf_5y_vs_spy_status,
        perf_5y_insufficient_history=perf_5y_insufficient_history,
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
        valuation_source=step3_out.valuation_source,
        fair_value_reported_currency=step3_out.inputs.reported_currency,
    )
