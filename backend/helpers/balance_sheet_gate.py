"""Newest-quarter balance-sheet completeness gate (Step 5 data path only).

FMP sometimes serves the newest quarterly balance sheet only partly filled in:
a line is remapped into a different one rather than really changing. The two
confirmed shapes (2026-10-05 investigation):

* debt remap -- long-term debt reads ~0 while total non-current liabilities
  stay flat (ZTS: longTermDebt 9,045M -> 190M, otherNonCurrentLiabilities
  500M -> 9,556M; also CIEN, LHX, GILD, TWLO, GEV, DOC, O, NEE). Debt/EBITDA
  then reads ~0 and scores "excellent".
* current-assets remap -- current assets collapse while total assets, total
  liabilities and current liabilities stay flat (ADP: 54,234M -> 8,603M,
  totalAssets -2%).

A genuine paydown shrinks total liabilities by about the same amount as the
debt (FSLR), so the debt rule requires that total liabilities did NOT follow
the debt down. When the newest quarter trips a rule it is treated as
incomplete and the PRIOR quarter's balance sheet is used instead -- a read-time
decision only: the incomplete row stays in the cache untouched (the refetch /
staleness policy is deliberately unchanged, see docs/specs/debt.md).

Pure calculation, no I/O. One step back only: if the prior quarter is itself
incomplete this does not walk further."""

from datetime import date, timedelta
from typing import NamedTuple

# Debt falls by this fraction or more versus the prior quarter ("65 percent or
# more", inclusive) ...
DEBT_DROP_THRESHOLD = 0.65
# ... AND total liabilities fall by LESS than this fraction of the absolute debt
# decline (a genuine paydown takes total liabilities down with it).
LIABILITIES_FOLLOW_FRACTION = 0.5
# ... AND the decline is material: at least this fraction of the prior
# quarter's total assets. Not part of the original brief -- added after a
# universe dry run showed the literal rule also fires on immaterial debt that
# genuinely went to zero (SHOP 16M, IONQ 9M, ALAB 6M, FFIV 33M, CRDO 21M, PDD
# 2.5B on a ~300B balance sheet: all <= 0.9% of assets) and, for SHOP, moved a
# Fail to a Strong Pass purely through the one-quarter window shift. Every real
# remap found sits at >= 3.4% (GEV 3.45%, TWLO 9.6%, CIEN 21%, ... ZTS 59%).
MATERIAL_DEBT_DECLINE_FRACTION_OF_ASSETS = 0.02
# Current assets fall by MORE than this fraction ("more than 60 percent",
# exclusive) while total liabilities, total assets AND current liabilities are
# each within FLAT_TOLERANCE of the prior quarter (ADP moved -1.7% / -2.0% /
# -3.8%). Current liabilities were added to the brief's "total liabilities and
# total assets roughly flat": a pure remap of current into non-current assets
# leaves them alone, while NDAQ's current liabilities rose 8x in the same
# quarter (a real restructuring, not a remap) and the literal rule flipped its
# Step 5 from Fail to Pass.
CURRENT_ASSETS_DROP_THRESHOLD = 0.60
FLAT_TOLERANCE = 0.05

# FMP's statements for one period carry the same period-end date, but a few
# filers differ by a day or two between statements. When aligning income/cash
# flow quarters to the balance sheet that is actually used, a row is only
# dropped when it ends more than this many days after that balance sheet.
ALIGN_TOLERANCE_DAYS = 10

DEBT_REMAP = "debt_remap"
CURRENT_ASSETS_REMAP = "current_assets_remap"

# Which "total debt" the debt rule watches -- the same definition the path
# being scored reads: Standard's Debt/EBITDA uses shortTermDebt + longTermDebt
# (helpers/debt_metrics.py), REIT gearing reads FMP's own totalDebt field.
DEBT_BASIS_SHORT_PLUS_LONG = "short_plus_long"
DEBT_BASIS_TOTAL_DEBT = "total_debt"


class BalanceSheetSelection(NamedTuple):
    row: dict
    # None when the newest quarter was kept.
    reason: str | None
    # Period-end date of the discarded newest quarter / of the row actually used.
    incomplete_date: str | None
    used_date: str | None
    detail: str | None

    @property
    def fallback_used(self) -> bool:
        return self.reason is not None


def _total_debt(row: dict, basis: str) -> float | None:
    if basis == DEBT_BASIS_TOTAL_DEBT:
        return row.get("totalDebt")
    short_term, long_term = row.get("shortTermDebt"), row.get("longTermDebt")
    if short_term is None and long_term is None:
        return None
    return (short_term or 0) + (long_term or 0)


def _debt_remap_detail(newest: dict, prior: dict, basis: str) -> str | None:
    debt_new, debt_prior = _total_debt(newest, basis), _total_debt(prior, basis)
    liabilities_new, liabilities_prior = newest.get("totalLiabilities"), prior.get("totalLiabilities")
    assets_prior = prior.get("totalAssets")
    if None in (debt_new, debt_prior, liabilities_new, liabilities_prior, assets_prior) or debt_prior <= 0:
        return None
    debt_decline = debt_prior - debt_new
    if debt_decline / debt_prior < DEBT_DROP_THRESHOLD:
        return None
    if assets_prior <= 0 or debt_decline / assets_prior < MATERIAL_DEBT_DECLINE_FRACTION_OF_ASSETS:
        return None
    liabilities_decline = liabilities_prior - liabilities_new
    if liabilities_decline >= LIABILITIES_FOLLOW_FRACTION * debt_decline:
        return None
    return (
        f"total debt {debt_prior:,.0f} -> {debt_new:,.0f} ({-debt_decline / debt_prior:+.0%}) while total "
        f"liabilities moved {liabilities_prior:,.0f} -> {liabilities_new:,.0f}"
    )


def _is_flat(new: float, prior: float) -> bool:
    return prior > 0 and abs(new - prior) / prior <= FLAT_TOLERANCE


def _current_assets_remap_detail(newest: dict, prior: dict) -> str | None:
    assets_new, assets_prior = newest.get("totalCurrentAssets"), prior.get("totalCurrentAssets")
    total_assets_new, total_assets_prior = newest.get("totalAssets"), prior.get("totalAssets")
    liabilities_new, liabilities_prior = newest.get("totalLiabilities"), prior.get("totalLiabilities")
    current_liabilities_new = newest.get("totalCurrentLiabilities")
    current_liabilities_prior = prior.get("totalCurrentLiabilities")
    if None in (
        assets_new,
        assets_prior,
        total_assets_new,
        total_assets_prior,
        liabilities_new,
        liabilities_prior,
        current_liabilities_new,
        current_liabilities_prior,
    ):
        return None
    if assets_prior <= 0 or (assets_prior - assets_new) / assets_prior <= CURRENT_ASSETS_DROP_THRESHOLD:
        return None
    if not (
        _is_flat(total_assets_new, total_assets_prior)
        and _is_flat(liabilities_new, liabilities_prior)
        and _is_flat(current_liabilities_new, current_liabilities_prior)
    ):
        return None
    return (
        f"current assets {assets_prior:,.0f} -> {assets_new:,.0f} ({(assets_new - assets_prior) / assets_prior:+.0%}) "
        f"while total assets, total liabilities and current liabilities stayed within {FLAT_TOLERANCE:.0%}"
    )


def select_complete_balance_sheet(
    balance_sheet_rows: list[dict], debt_basis: str, check_current_assets: bool
) -> BalanceSheetSelection:
    """`balance_sheet_rows` most-recent-first (FMP's own ordering). Returns the
    newest row unless it trips a completeness rule, in which case the prior
    quarter's row. `check_current_assets` is True only for the path that reads
    current assets (Standard's Current Ratio); the REIT path does not."""
    if not balance_sheet_rows:
        return BalanceSheetSelection({}, None, None, None, None)
    newest = balance_sheet_rows[0]
    if len(balance_sheet_rows) < 2:
        return BalanceSheetSelection(newest, None, None, newest.get("date"), None)
    prior = balance_sheet_rows[1]

    reason, detail = None, _debt_remap_detail(newest, prior, debt_basis)
    if detail is not None:
        reason = DEBT_REMAP
    elif check_current_assets:
        detail = _current_assets_remap_detail(newest, prior)
        if detail is not None:
            reason = CURRENT_ASSETS_REMAP

    if reason is None:
        return BalanceSheetSelection(newest, None, None, newest.get("date"), None)
    return BalanceSheetSelection(prior, reason, newest.get("date"), prior.get("date"), detail)


def align_quarters_to_balance_sheet(rows: list[dict], balance_sheet_date: str | None) -> list[dict]:
    """Drop the leading (newest) income/cash-flow quarters that end after the
    balance sheet actually used, so every statement's TTM window ends on the
    same period. `rows` most-recent-first. A row ending within
    ALIGN_TOLERANCE_DAYS of the balance sheet date, or with no parseable date,
    is kept; only the contiguous newest run is ever dropped."""
    if not balance_sheet_date:
        return rows
    try:
        cutoff = date.fromisoformat(balance_sheet_date[:10]) + timedelta(days=ALIGN_TOLERANCE_DAYS)
    except ValueError:
        return rows
    kept_from = 0
    for row in rows:
        try:
            row_date = date.fromisoformat((row.get("date") or "")[:10])
        except ValueError:
            break
        if row_date <= cutoff:
            break
        kept_from += 1
    return rows[kept_from:]
