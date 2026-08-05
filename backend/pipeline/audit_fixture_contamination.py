"""Standalone script: scans FundamentalsCache for the class of test-fixture
contamination confirmed in the 2026-07-28 "Acme Corp" / PEP incident (see
CLAUDE.md's "Ad-hoc reproduction scripts must not touch the real database").
That incident happened because an ad-hoc script mirrored a test's fixture/
monkeypatch setup but only patched fmp_client, not the module's `engine`,
so cache.py::get_or_fetch silently persisted the test's fake profile/
income_statement/cash_flow_statement rows into the real database under a
real ticker symbol.

Read-only -- never deletes or modifies anything. Flags a candidate row for
manual review; a hit here is not proof of contamination on its own (e.g. a
company genuinely named "Sample Inc" would false-positive on the name
check), just a reason to look closer the way this investigation did.

Run anytime, no FMP calls, no writes:
    uv run python -m pipeline.audit_fixture_contamination
"""

import json

from sqlmodel import Session, select

from db import engine, init_db
from first import _first
from models import FundamentalsCache

# Case-insensitive substrings that showed up in the confirmed incident's
# fixture data (backend/tests/test_debt_metrics.py::PROFILE) or are the
# generic hallmarks of placeholder/test company names in general.
SUSPECT_NAME_SUBSTRINGS = ("acme", "test", "placeholder", "dummy", "sample", "example corp")

# The confirmed incident's exact cash-flow fixture value
# (CASH_FLOW_QUARTERLY in test_debt_metrics.py) -- a real company can
# genuinely report this by coincidence, so this is only ever combined with
# the duplicate-date check below, never flagged alone.
FIXTURE_CFO_VALUE = 10_000_000_000


def _check_profile(ticker: str, data) -> list[str]:
    row = _first(data)
    name = (row.get("companyName") or "").lower()
    hits = [s for s in SUSPECT_NAME_SUBSTRINGS if s in name]
    if hits:
        return [f"companyName={row.get('companyName')!r} matches suspect substring(s) {hits}"]
    return []


def _check_income_statement(ticker: str, data) -> list[str]:
    if not isinstance(data, list) or not data:
        return []
    first = data[0]
    if not isinstance(first, dict):
        return []
    # Every real FMP income-statement row has both fields; the confirmed
    # incident's fixture had neither (only ebitda/interestExpense/
    # interestIncome/netInterestIncome).
    if "revenue" not in first and "netIncome" not in first:
        return ["row(s) missing both 'revenue' and 'netIncome' -- not a real FMP income-statement shape"]
    return []


def _check_cash_flow_statement(ticker: str, data) -> list[str]:
    if not isinstance(data, list) or len(data) < 2:
        return []
    dates = [row.get("date") for row in data if isinstance(row, dict)]
    duplicate_dates = len(dates) != len(set(dates))
    all_same_cfo_value = all(
        isinstance(row, dict) and row.get("netCashProvidedByOperatingActivities") == FIXTURE_CFO_VALUE for row in data
    )
    if duplicate_dates and all_same_cfo_value:
        return [f"all {len(data)} rows share a duplicate date and identical CFO={FIXTURE_CFO_VALUE:,}"]
    return []


CHECKS = {
    "profile": _check_profile,
    "income_statement": _check_income_statement,
    "cash_flow_statement": _check_cash_flow_statement,
}


def run_audit() -> list[tuple[str, str, str, str]]:
    """Returns a list of (ticker, statement_type, period, reason) findings."""
    findings = []
    with Session(engine) as session:
        rows = session.exec(
            select(FundamentalsCache).where(FundamentalsCache.statement_type.in_(CHECKS.keys()))
        ).all()
        for row in rows:
            check = CHECKS[row.statement_type]
            try:
                data = json.loads(row.raw_json)
            except (json.JSONDecodeError, TypeError):
                continue
            for reason in check(row.ticker, data):
                findings.append((row.ticker, row.statement_type, row.period, reason))
    return findings


def main() -> None:
    init_db()
    findings = run_audit()
    if not findings:
        print("No fixture-contamination fingerprints found.")
        return
    print(f"{len(findings)} suspect row(s) found -- review manually, this is not automatic proof of contamination:")
    for ticker, statement_type, period, reason in findings:
        print(f"  {ticker} {statement_type}/{period}: {reason}")


if __name__ == "__main__":
    main()
