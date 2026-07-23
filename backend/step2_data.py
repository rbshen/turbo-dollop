from datetime import date

from sqlmodel import Session, select

from cache import get_or_fetch, safe_fetch
from config import settings
from db import engine
from fmp_client import fmp_client
from models import GrowthCatalystNote
from schemas import Step2EstimateRow, Step2Out
from scoring.step2 import score_step2

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
    ticker = ticker.upper()
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
        growth_catalysts = _get_growth_catalysts(session, ticker)

    estimates = estimates_data if isinstance(estimates_data, list) else []
    rows = _future_rows(estimates, today)

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
        # No real growth rate to score -- explicitly Fail rather than
        # feeding a fabricated 0.0 growth rate through score_step2, which
        # would now read as non-negative and pass under the magnitude-gated
        # verdict logic below.
        return Step2Out(
            ticker=ticker,
            basis=None,
            estimates=[],
            growth_catalysts=growth_catalysts,
            score=0,
            verdict="Fail",
            components={
                "magnitude": {"score": 0},
                "agreement": {"score": 0},
                "insufficient_data": True,
            },
        )

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
        score=result.score,
        verdict=result.verdict,
        components={
            "magnitude": {"score": result.magnitude_score, "growth_rate": projection["growth_rate"]},
            "agreement": {"score": result.agreement_score, "spread": projection["spread"]},
        },
    )
