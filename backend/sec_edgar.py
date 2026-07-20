import logging
from datetime import date
from typing import Callable, NamedTuple

import httpx
from sqlmodel import Session

from cache import get_or_fetch
from config import settings
from fmp_client import fmp_client

logger = logging.getLogger(__name__)

COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Confirmed during investigation: both PEP and OXM independently changed
# which of these tags they use for interest expense over time -- never
# guess a single one, always try in order and use whichever has an entry
# covering the target period.
INTEREST_EXPENSE_CANDIDATE_TAGS = [
    "InterestExpense",
    "InterestIncomeExpenseNet",
    "InterestIncomeExpenseNonoperatingNet",
    "InterestExpenseDebt",
]
# CFO is far more standardized than interest expense -- essentially one
# tag, with a second variant for companies that break out discontinued
# operations separately.
CFO_CANDIDATE_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]

# A discrete fiscal quarter runs roughly ~3 months -- wide enough to cover
# 12-week, 13-week, and calendar-month quarter conventions, tight enough to
# reject the YTD (6/9/12-month) entries also present under the same tag.
DISCRETE_QUARTER_MIN_DAYS = 60
DISCRETE_QUARTER_MAX_DAYS = 100

# FMP-vs-SEC relative tolerance for "this confirms FMP's figure" -- wider
# than a strict equality check to absorb minor rounding/period-alignment
# noise, tight enough that anything resembling PEP's real ~10x error is
# unambiguously still flagged as a discrepancy. A small absolute floor
# handles the case where the SEC value itself is 0 or very small.
MATCH_RELATIVE_TOLERANCE = 0.10
MATCH_ABSOLUTE_FLOOR = 1.0


class CrossCheckResult(NamedTuple):
    available: bool
    sec_value: float | None
    tag_used: str | None
    matches_fmp: bool | None
    note: str


async def get_cik(session: Session, ticker: str, staleness_days: int) -> int | None:
    """Ticker -> CIK read from FMP's own /profile.cik field (already a
    zero-padded 10-digit string, e.g. "0000077476" for PEP -- confirmed live
    to match the real SEC CIK exactly) rather than SEC's own ticker->CIK map
    (www.sec.gov/files/company_tickers.json). That host is blocked at the
    Akamai edge for this VPS's IP -- data.sec.gov (the actual XBRL fetch
    below) is unaffected, so this removes the www.sec.gov dependency
    entirely. Cached under the same "profile"/"latest" key every other
    pipeline already populates, so this is very often a cache hit, not a
    new FMP call."""
    ticker = ticker.upper()
    profile = await get_or_fetch(session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days)
    row = profile[0] if isinstance(profile, list) and profile else profile
    if not isinstance(row, dict):
        return None
    cik = row.get("cik")
    if not cik:
        return None
    try:
        return int(cik)
    except (TypeError, ValueError):
        return None


async def _fetch_company_facts(cik: int) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            COMPANY_FACTS_URL_TEMPLATE.format(cik=cik), headers={"User-Agent": settings.sec_edgar_user_agent}
        )
        response.raise_for_status()
        return response.json()


async def get_company_facts(session: Session, ticker: str, cik: int, staleness_days: int) -> dict:
    """Cached exactly like every other per-ticker fetch -- ticker as the
    cache key, a dedicated statement_type so it never collides with FMP's
    own cache rows for the same ticker."""
    return await get_or_fetch(
        session, ticker, "sec_company_facts", "latest", lambda: _fetch_company_facts(cik), staleness_days
    )


def _duration_days(row: dict) -> int:
    return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days


def find_discrete_income_statement_value(
    facts: dict, tag_candidates: list[str], target_end: date
) -> tuple[float, str] | None:
    """Interest expense (and similar income-statement concepts): confirmed
    live that these are dual-tagged with both a YTD and a discrete-quarter
    duration in the same filing (both PEP and OXM), so a direct end-date +
    duration-window match finds the discrete figure -- no YTD subtraction
    needed here, unlike CFO below."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    target_end_str = target_end.isoformat()
    for tag in tag_candidates:
        concept = gaap.get(tag)
        if not concept:
            continue
        candidates = [
            row
            for row in concept.get("units", {}).get("USD", [])
            if row.get("end") == target_end_str
            and DISCRETE_QUARTER_MIN_DAYS <= _duration_days(row) <= DISCRETE_QUARTER_MAX_DAYS
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda r: r.get("filed", ""))  # most-recently-filed, in case of a later restatement
        return best["val"], tag
    return None


def find_discrete_cfo_value(facts: dict, tag_candidates: list[str], target_end: date) -> tuple[float, str] | None:
    """CFO: cash-flow-statement concepts are only ever tagged YTD-cumulative
    (confirmed live for PEP -- no discrete-quarter duration exists beyond
    Q1, since that's how GAAP cash flow statements are actually presented).
    Discrete quarter = (YTD-through-target) - (YTD-through-the-immediately-
    preceding same-fiscal-year period). If no earlier same-fiscal-year
    entry exists, target_end IS the fiscal year's first quarter, and the
    YTD value already IS the discrete value."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    target_end_str = target_end.isoformat()
    for tag in tag_candidates:
        concept = gaap.get(tag)
        if not concept:
            continue
        rows = concept.get("units", {}).get("USD", [])
        target_matches = [row for row in rows if row.get("end") == target_end_str]
        if not target_matches:
            continue
        target_row = max(target_matches, key=lambda r: r.get("filed", ""))
        fiscal_year_start = target_row["start"]

        # Same fiscal year (same start date), strictly earlier end -- the
        # prior quarter-end within this same fiscal year, not just
        # whatever the second-most-recent entry happens to be.
        same_year_prior = [row for row in rows if row.get("start") == fiscal_year_start and row["end"] < target_end_str]
        if not same_year_prior:
            return target_row["val"], tag

        latest_prior_end = max(row["end"] for row in same_year_prior)
        prior_candidates = [row for row in same_year_prior if row["end"] == latest_prior_end]
        prior_row = max(prior_candidates, key=lambda r: r.get("filed", ""))
        return target_row["val"] - prior_row["val"], tag
    return None


async def _cross_check(
    session: Session,
    ticker: str,
    target_end: date,
    fmp_value: float,
    staleness_days: int,
    tag_candidates: list[str],
    finder: Callable[[dict, list[str], date], tuple[float, str] | None],
    label: str,
) -> CrossCheckResult:
    try:
        cik = await get_cik(session, ticker, staleness_days)
        if cik is None:
            return CrossCheckResult(False, None, None, None, f"SEC EDGAR cross-check unavailable: no CIK found for {ticker}.")

        facts = await get_company_facts(session, ticker, cik, staleness_days)
        found = finder(facts, tag_candidates, target_end)
        if found is None:
            return CrossCheckResult(
                False, None, None, None, f"SEC EDGAR cross-check unavailable: no matching {label} figure found for this period."
            )

        sec_value, tag_used = found
        tolerance = max(abs(sec_value) * MATCH_RELATIVE_TOLERANCE, MATCH_ABSOLUTE_FLOOR)
        matches = abs(fmp_value - sec_value) <= tolerance
        note = (
            "SEC EDGAR confirms FMP's figure."
            if matches
            else "FMP's figure appears to be a data error -- SEC EDGAR's filed value differs significantly."
        )
        return CrossCheckResult(True, sec_value, tag_used, matches, note)
    except httpx.HTTPError as exc:
        logger.warning("SEC EDGAR cross-check failed for %s: %s", ticker, exc)
        return CrossCheckResult(False, None, None, None, "SEC EDGAR cross-check unavailable (network error).")


async def cross_check_interest_expense(
    session: Session, ticker: str, target_end: date, fmp_value: float, staleness_days: int
) -> CrossCheckResult:
    return await _cross_check(
        session,
        ticker,
        target_end,
        fmp_value,
        staleness_days,
        INTEREST_EXPENSE_CANDIDATE_TAGS,
        find_discrete_income_statement_value,
        "interest expense",
    )


async def cross_check_cfo(
    session: Session, ticker: str, target_end: date, fmp_value: float, staleness_days: int
) -> CrossCheckResult:
    return await _cross_check(
        session, ticker, target_end, fmp_value, staleness_days, CFO_CANDIDATE_TAGS, find_discrete_cfo_value, "CFO"
    )
