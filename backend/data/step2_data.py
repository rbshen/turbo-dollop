from datetime import date

from sqlmodel import Session, select

from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from clients.fmp_client import fmp_client
from core.models import GrowthCatalystNote
from core.schemas import Step2EstimateRow, Step2Out
from core.tickers import normalize_ticker
from helpers.first import _first
from scoring.classification import classify_company_type
from scoring.step2 import AGREEMENT_WEIGHT, MAGNITUDE_WEIGHT, score_step2
from scoring.step3 import dpu_growth_note

WEIGHTS = {"magnitude": MAGNITUDE_WEIGHT, "agreement": AGREEMENT_WEIGHT}

# REITs are routed straight to Revenue (rental income) growth, never EPS --
# FMP has no forward-looking DPU/dividend estimate field at all (checked:
# /analyst-estimates rows only carry revenue/ebitda/ebit/netIncome/
# sgaExpense/eps fields), and REIT revenue is already ~95-100% rental income
# across the tracked universe (confirmed via revenue_product_segmentation on
# ARE/AVB/O) -- so Revenue growth IS rental-income growth for this company
# type, not just a fallback proxy. See CLAUDE.md's REIT framework
# investigation.
REIT_GROWTH_BASIS_NOTE = (
    "REITs are scored on revenue (rental income) growth rather than DPU, since forward DPU/dividend "
    "estimates aren't available from the data provider -- REIT revenue is effectively rental income for "
    "this universe."
)

# The 3-5yr horizon the source doc asks for, centered on 4 years out --
# same window ticker_summary.py already uses for the header's EPS CAGR.
TARGET_WINDOW_MIN_YEARS = 3
TARGET_WINDOW_MAX_YEARS = 5
TARGET_WINDOW_CENTER_YEARS = 4


def _future_rows(rows: list[dict], today: date) -> list[dict]:
    """Forward-dated estimate rows only, oldest first -- FMP's response
    includes already-past years too, which the Step 2 doc explicitly says
    not to substitute for real forward projections."""
    dated = [row for row in rows if row.get("date")]
    future = [row for row in dated if date.fromisoformat(row["date"][:10]) > today]
    return sorted(future, key=lambda r: r["date"])


def _year_offset(rows_base_year: int, row: dict) -> int:
    return date.fromisoformat(row["date"][:10]).year - rows_base_year


def _project(rows: list[dict], avg_field: str, low_field: str, high_field: str, analysts_field: str) -> dict | None:
    """CAGR from the nearest forward estimate to the forward estimate
    closest to 4 years out, plus that target year's high/low spread as a %
    of its average -- see CLAUDE.md's Step 2 data-source substitution."""
    if len(rows) < 2:
        return None

    base = rows[0]
    base_year = date.fromisoformat(base["date"][:10]).year
    later = rows[1:]
    in_window = [r for r in later if TARGET_WINDOW_MIN_YEARS <= _year_offset(base_year, r) <= TARGET_WINDOW_MAX_YEARS]
    candidates = in_window if in_window else later
    # FMP sometimes reports 0 for avg_field on sparsely-covered far-out
    # years even when a nearer year in the same pool has a real estimate --
    # prefer a usable row over blindly picking whatever's closest to the
    # window center. Falls back to the full pool only if nothing in it has
    # real data, so a genuinely all-null/zero pool still surfaces as None
    # downstream rather than masking the gap.
    usable = [r for r in candidates if r.get(avg_field)]
    pool = usable if usable else candidates
    target = min(pool, key=lambda r: abs(_year_offset(base_year, r) - TARGET_WINDOW_CENTER_YEARS))

    base_val = base.get(avg_field)
    target_val = target.get(avg_field)
    years = _year_offset(base_year, target)
    if not base_val or base_val <= 0 or not target_val or years <= 0:
        return None

    growth_rate = ((target_val / base_val) ** (1 / years) - 1) * 100

    high, low, avg = target.get(high_field), target.get(low_field), target.get(avg_field)
    spread = (high - low) / avg * 100 if high is not None and low is not None and avg else None

    table = [
        Step2EstimateRow(
            fiscal_year=str(date.fromisoformat(row["date"][:10]).year),
            growth_avg=(row[avg_field] / base_val - 1) * 100,
            growth_high=(row[high_field] / base_val - 1) * 100,
            growth_low=(row[low_field] / base_val - 1) * 100,
        )
        for row in later
        if row.get(avg_field) is not None and row.get(high_field) is not None and row.get(low_field) is not None
    ]

    return {
        "base_fiscal_year": str(base_year),
        "target_fiscal_year": str(date.fromisoformat(target["date"][:10]).year),
        "growth_rate": growth_rate,
        "spread": spread,
        "table": table,
        # Informational only -- doesn't affect the score, just lets the UI
        # show how many analysts the agreement spread is actually built on.
        "analyst_count": target.get(analysts_field),
    }


def _get_growth_catalysts(session: Session, ticker: str) -> str | None:
    row = session.exec(select(GrowthCatalystNote).where(GrowthCatalystNote.ticker == ticker)).first()
    return row.notes if row else None


async def get_step2_data(ticker: str, cache_only: bool = False) -> Step2Out:
    """`cache_only=True` (used by ticker_score.py's recompute path) reads
    only whatever's already cached and never calls FMP -- see
    cache.get_or_fetch's own cache_only branch."""
    ticker = normalize_ticker(ticker)
    staleness_days = settings.cache_staleness_days
    today = date.today()

    with Session(engine) as session:
        estimates_data = await safe_fetch(
            "analyst_estimates",
            get_or_fetch(
                session,
                ticker,
                "analyst_estimates",
                "latest",
                lambda: fmp_client.get_analyst_estimates(ticker),
                staleness_days,
                cache_only,
            ),
        )
        # Same cache key ("profile"/"latest") Step 1/4/5 already populate --
        # a cache hit, not a new fetch, for any ticker already scored
        # elsewhere in the app.
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
                ),
            )
        )
        company_type = classify_company_type(profile.get("sector"), profile.get("industry"), ticker)
        is_reit = company_type == "REIT/Property Developer"

        dpu_note = None
        if is_reit:
            # Only fetched for REITs -- same cache key ("ratios"/"annual_10y")
            # step3_data.py already populates for the Valuation P/B lookback,
            # so this is a cache hit whenever that tab's been viewed, and one
            # new incremental fetch otherwise. Never fetched for the ~500
            # non-REIT tickers.
            ratios_annual = await safe_fetch(
                "ratios_annual_10y",
                get_or_fetch(
                    session,
                    ticker,
                    "ratios",
                    "annual_10y",
                    lambda: fmp_client.get_ratios(ticker, "annual", 10),
                    staleness_days,
                    cache_only,
                ),
            )
            ratios_annual = ratios_annual if isinstance(ratios_annual, list) else []
            dpu_series = list(reversed([row.get("dividendPerShare") for row in ratios_annual]))
            dpu_note = dpu_growth_note(dpu_series)

        growth_catalysts = _get_growth_catalysts(session, ticker)

    estimates = estimates_data if isinstance(estimates_data, list) else []
    rows = _future_rows(estimates, today)

    if is_reit:
        # REITs skip the EPS attempt entirely, not just fall back past it --
        # EPS is depreciation-heavy and doesn't reflect REIT economics (see
        # CLAUDE.md's REIT framework investigation). Revenue is effectively
        # rental income for this company type.
        projection = _project(rows, "revenueAvg", "revenueLow", "revenueHigh", "numAnalystsRevenue")
        basis = "revenue"
    else:
        # Prefer EPS estimates -- less exposed to the "insufficient data" gap
        # revenue-only sourcing had, and the basis this app's methodology now
        # standardizes on (see CLAUDE.md's Step 2 rationale). Fall back to
        # revenue if EPS doesn't yield a usable CAGR for this ticker (most
        # commonly a negative base-year EPS, which makes a CAGR mathematically
        # undefined even when the field itself is populated).
        projection = _project(rows, "epsAvg", "epsLow", "epsHigh", "numAnalystsEps")
        basis = "eps"
        if projection is None:
            projection = _project(rows, "revenueAvg", "revenueLow", "revenueHigh", "numAnalystsRevenue")
            basis = "revenue"

    if projection is None:
        # No real growth rate to score -- neither EPS nor Revenue yielded a
        # usable CAGR (too few/no future analyst estimate rows, which also
        # covers a failed FMP fetch: safe_fetch swallows the exception to
        # `{}`, indistinguishable downstream from a genuinely-thin response).
        # This is a data gap, not evidence of poor growth -- score=None/
        # verdict="insufficient_data" (Step4Out/Step5Out's own convention)
        # rather than a fabricated scored Fail, which previously collapsed
        # "we have no data" and "this company is failing" into the same
        # verdict feeding Overall Assessment and the Screener.
        return Step2Out(
            ticker=ticker,
            basis=None,
            estimates=[],
            growth_catalysts=growth_catalysts,
            score=None,
            verdict="insufficient_data",
            weights=WEIGHTS,
        )

    growth_basis_note = REIT_GROWTH_BASIS_NOTE if is_reit else None

    result = score_step2(growth_rate_pct=projection["growth_rate"], spread_pct=projection["spread"] or 100.0)

    return Step2Out(
        ticker=ticker,
        basis=basis,
        estimates=projection["table"],
        base_fiscal_year=projection["base_fiscal_year"],
        target_fiscal_year=projection["target_fiscal_year"],
        growth_rate=projection["growth_rate"],
        estimate_spread=projection["spread"],
        target_analyst_count=projection["analyst_count"],
        growth_catalysts=growth_catalysts,
        growth_basis_note=growth_basis_note,
        dpu_growth_note=dpu_note,
        score=result.score,
        verdict=result.verdict,
        components={
            "magnitude": {
                "score": result.magnitude_score,
                "tier": result.magnitude_tier,
                "growth_rate": projection["growth_rate"],
            },
            "agreement": {
                "score": result.agreement_score,
                "tier": result.agreement_tier,
                "spread": projection["spread"],
            },
        },
        weights=WEIGHTS,
    )
