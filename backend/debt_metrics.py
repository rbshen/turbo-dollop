from typing import NamedTuple

from ttm import sum_last_four_quarters


class DebtMetrics(NamedTuple):
    total_debt: float | None
    ebitda_ttm: float | None
    net_interest_expense_ttm: float | None


def compute_debt_metrics(balance_sheet_row: dict, income_quarterly: list[dict]) -> DebtMetrics:
    """Latest-quarter total debt (short + long term) and TTM EBITDA / net
    interest expense -- pure calculation shared by Step 5's debt ratios
    (`step5_data.py`'s Standard path) and the ticker header's raw metric
    tiles (`ticker_summary.py`), so the two views can never show
    inconsistent numbers for the same ticker. No I/O here -- each caller
    fetches `balance_sheet_row` (latest quarterly snapshot) and
    `income_quarterly` (last 4 quarters) itself, using the same cache
    keys/limits Step 1/Step 5 already populate (see CLAUDE.md's caching
    policy and the Step 5 data-freshness fix in 2f3cc98).

    Applies uniformly to every company type: these are raw figures, not
    Step 5's classified ratios, so there's no Bank/REIT exemption here."""
    short_term_debt = balance_sheet_row.get("shortTermDebt")
    long_term_debt = balance_sheet_row.get("longTermDebt")
    total_debt = (
        (short_term_debt or 0) + (long_term_debt or 0)
        if short_term_debt is not None or long_term_debt is not None
        else None
    )

    ebitda_ttm = sum_last_four_quarters(income_quarterly, "ebitda")
    net_interest_income_ttm = sum_last_four_quarters(income_quarterly, "netInterestIncome")
    # A company earning net interest income has no interest burden for this
    # purpose (clamped at 0, not left negative) -- same convention as
    # Step 5's Debt Servicing Ratio.
    net_interest_expense_ttm = max(0.0, -net_interest_income_ttm) if net_interest_income_ttm is not None else None

    return DebtMetrics(total_debt=total_debt, ebitda_ttm=ebitda_ttm, net_interest_expense_ttm=net_interest_expense_ttm)
