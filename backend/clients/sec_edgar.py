import logging
from datetime import date
from typing import Callable, NamedTuple

import httpx
from sqlmodel import Session

from core.cache import get_or_fetch
from core.config import settings
from core.tickers import normalize_ticker
from clients.fmp_client import fmp_client

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

# Full fiscal year -- same widening logic as the quarter window above, just
# scaled to ~12 months instead of ~3.
ANNUAL_DURATION_MIN_DAYS = 330
ANNUAL_DURATION_MAX_DAYS = 380

# Phase 3a (2026-08-16): supplemental cash-flow-statement disclosures,
# confirmed to have a genuine FMP data gap (see CLAUDE.md /
# FinancialsStatementTable.tsx's INCOMPLETE_COVERAGE_LABELS -- FMP reads a
# literal 0 for every period for a meaningful slice of tickers, e.g. MSFT).
# Tags confirmed live against MSFT's real SEC company-facts data (not
# guessed): IncomeTaxesPaidNet is used for FY2025/FY2026 ($28.7B/$21.19B),
# InterestPaid for the same years ($1.6B/$1.5B) -- both read as 0 in FMP's
# cache for every cached period. The non-"Net" IncomeTaxesPaid and the
# "Net" InterestPaidNet variants are kept as fallbacks for filers who tag
# differently, mirroring INTEREST_EXPENSE_CANDIDATE_TAGS's own multi-tag
# convention -- not verified against a second filer the way that list was,
# since only these two fields were in scope for this pass.
INCOME_TAXES_PAID_CANDIDATE_TAGS = ["IncomeTaxesPaidNet", "IncomeTaxesPaid"]
INTEREST_PAID_CANDIDATE_TAGS = ["InterestPaid", "InterestPaidNet"]

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


async def get_cik(session: Session, ticker: str, staleness_days: int, cache_only: bool = False) -> int | None:
    """Ticker -> CIK read from FMP's own /profile.cik field (already a
    zero-padded 10-digit string, e.g. "0000077476" for PEP -- confirmed live
    to match the real SEC CIK exactly) rather than SEC's own ticker->CIK map
    (www.sec.gov/files/company_tickers.json). That host is blocked at the
    Akamai edge for this VPS's IP -- data.sec.gov (the actual XBRL fetch
    below) is unaffected, so this removes the www.sec.gov dependency
    entirely. Cached under the same "profile"/"latest" key every other
    pipeline already populates, so this is very often a cache hit, not a
    new FMP call.

    cache_only previously had no way to reach this call at all (silently
    hardcoded to the get_or_fetch default of False) -- now threaded through
    like every other FMP-backed fetch in this codebase, so a caller that
    needs a cache-only read can actually get one. In practice this is
    covered automatically whenever settings.fmp_enabled is False too, via
    get_or_fetch's own check -- this parameter exists for the same explicit
    per-call cache_only control every other module already has."""
    ticker = normalize_ticker(ticker)
    profile = await get_or_fetch(
        session, ticker, "profile", "latest", lambda: fmp_client.get_profile(ticker), staleness_days, cache_only
    )
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


def find_annual_value(facts: dict, tag_candidates: list[str], target_end: date) -> tuple[float, str] | None:
    """Full-fiscal-year supplemental cash-flow disclosures (Income Taxes
    Paid, Interest Paid): FMP's own annual cash-flow-statement figure for a
    fiscal year IS the YTD-cumulative XBRL fact as of that fiscal year's own
    end date -- unlike CFO's discrete-quarter reconciliation
    (find_discrete_cfo_value), no subtraction is needed here, just a direct
    end-date + full-year-duration match. Confirmed live against MSFT: FY2025
    (2024-07-01..2025-06-30) IncomeTaxesPaidNet=$28.7B, InterestPaid=$1.6B --
    both real, non-zero, and currently misread as a literal 0 in FMP's own
    cached data for every period (see INCOME_TAXES_PAID_CANDIDATE_TAGS)."""
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
            and ANNUAL_DURATION_MIN_DAYS <= _duration_days(row) <= ANNUAL_DURATION_MAX_DAYS
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
        if facts is None:
            # Only reachable when FMP_ENABLED is False and this ticker's
            # sec_company_facts row has never been cached (get_or_fetch
            # returns None rather than fetching live) -- degrade the same
            # way a missing CIK does, don't let finder() below blow up on a
            # None facts dict.
            return CrossCheckResult(
                False,
                None,
                None,
                None,
                f"SEC EDGAR cross-check unavailable: no cached company facts for {ticker} and live fetch is disabled.",
            )
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


async def cross_check_income_taxes_paid(
    session: Session, ticker: str, target_end: date, fmp_value: float, staleness_days: int
) -> CrossCheckResult:
    return await _cross_check(
        session,
        ticker,
        target_end,
        fmp_value,
        staleness_days,
        INCOME_TAXES_PAID_CANDIDATE_TAGS,
        find_annual_value,
        "Income Taxes Paid",
    )


async def cross_check_interest_paid(
    session: Session, ticker: str, target_end: date, fmp_value: float, staleness_days: int
) -> CrossCheckResult:
    return await _cross_check(
        session, ticker, target_end, fmp_value, staleness_days, INTEREST_PAID_CANDIDATE_TAGS, find_annual_value, "Interest Paid"
    )
