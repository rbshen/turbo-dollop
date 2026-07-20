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
# as unavailable, same as a missing tag.
MIN_LOANS_TO_ASSETS_RATIO = 0.10


class NplResult(NamedTuple):
    ratio_pct: float | None


def compute_npl_ratio(raw_reported: dict, total_assets: float | None) -> NplResult:
    """Pure function: nonaccrual loans / total loans * 100, computed
    manually from raw tags -- never trusts a bank's own pre-computed ratio
    tag, since those aren't standardized (one bank's pre-computed ratio
    means "percent of total loans", another's means "percent past due", not
    the same metric despite similar naming)."""
    nonaccrual = raw_reported.get(NONACCRUAL_TAG)
    total_loans = raw_reported.get(TOTAL_LOANS_TAG)

    if nonaccrual is None or not total_loans:
        return NplResult(ratio_pct=None)

    if total_assets and total_loans < total_assets * MIN_LOANS_TO_ASSETS_RATIO:
        return NplResult(ratio_pct=None)

    return NplResult(ratio_pct=nonaccrual / total_loans * 100)
