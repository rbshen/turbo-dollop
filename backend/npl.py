from typing import NamedTuple

# XBRL tags pulled from FMP's raw /financial-statement-full-as-reported dump
# -- confirmed present and correctly scoped (see below) for JPM and USB, but
# NOT reliable across all banks: this endpoint is a flat dump of whatever
# tags each filer's own XBRL used, not a standardized schema.
NONACCRUAL_TAG = "financingreceivableexcludingaccruedinterestnonaccrual"
TOTAL_LOANS_TAG = "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss"

# A bank's loan book should be a substantial fraction of its balance sheet.
# Investigation confirmed TOTAL_LOANS_TAG resolves to the correct
# consolidated total for some banks (JPM: 31.8% of total assets, USB: 54.8%)
# but to a mis-scoped, far-too-small disclosure-table value for others (BAC:
# 0.03%, WFC: 1.4%, C: 1.9%) -- almost certainly a different XBRL context/
# dimension member with the same tag name, not the real total. Rather than
# guess at an alternate tag per bank, any result below this floor is treated
# as unavailable, same as a missing tag. Applies regardless of which period
# (quarterly or annual-fallback) the figures came from.
MIN_LOANS_TO_ASSETS_RATIO = 0.10


class NplResult(NamedTuple):
    ratio_pct: float | None
    # Which filing the figure is actually as-of, e.g. "Q2 2026" or "FY2025
    # annual filing" -- None whenever ratio_pct is None. Set so a
    # fallback-sourced figure is never presented as equally current as one
    # read straight from the latest quarter.
    as_of: str | None


def _extract(row: dict) -> tuple[float | None, float | None]:
    data = row.get("data") or {}
    return data.get(NONACCRUAL_TAG), data.get(TOTAL_LOANS_TAG)


def _label_for(row: dict) -> str:
    period = row.get("period")
    fiscal_year = row.get("fiscalYear")
    if period == "FY":
        return f"FY{fiscal_year} annual filing" if fiscal_year else "annual filing"
    if period and fiscal_year:
        return f"{period} {fiscal_year}"
    return row.get("date") or "latest filing"


def compute_npl_ratio(quarterly_row: dict, annual_row: dict, total_assets: float | None) -> NplResult:
    """Pure function: nonaccrual loans / total loans * 100, computed
    manually from raw tags -- never trusts a bank's own pre-computed ratio
    tag, since those aren't standardized (one bank's pre-computed ratio
    means "percent of total loans", another's means "percent past due", not
    the same metric despite similar naming).

    The nonaccrual-loan disclosure is sometimes 10-K-only for a given filer
    (confirmed for USB and TFC: present annually, absent from the latest
    10-Q) -- when the latest quarter's nonaccrual tag is specifically
    missing, this falls back to the annual filing's own figures (both
    nonaccrual and total_loans from that same filing, never mixed across
    periods). It does NOT fall back when total_loans alone looks wrong
    (BAC/WFC/C/PNC/MTB's failure mode) -- that's a different, unrelated
    problem the plausibility floor already handles."""
    nonaccrual, total_loans = _extract(quarterly_row)
    source_row = quarterly_row

    if nonaccrual is None:
        nonaccrual, total_loans = _extract(annual_row)
        source_row = annual_row

    if nonaccrual is None or not total_loans:
        return NplResult(ratio_pct=None, as_of=None)

    if total_assets and total_loans < total_assets * MIN_LOANS_TO_ASSETS_RATIO:
        return NplResult(ratio_pct=None, as_of=None)

    return NplResult(ratio_pct=nonaccrual / total_loans * 100, as_of=_label_for(source_row))
