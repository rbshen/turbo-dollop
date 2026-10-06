"""The cleaned-statement loader: one place that turns cached FMP statements into what the scored path reads
(docs/specs/statement-data-quality.md, "The shared loader").

Everything here reuses the existing rule helpers unchanged -- `ttm.clean_cash_flow_statements` (placeholder and
scale-break cash-flow rows), `balance_sheet_gate.select_complete_balance_sheet` / `align_quarters_to_balance_sheet`
(newest-quarter completeness gate, prior-quarter fallback, income/cash-flow alignment), `debt_metrics.compute_debt_metrics`
and the Defect-B-aware `ttm.sum_last_four_quarters`. The order is the one `get_step5_data` always used:

    clean the cash-flow rows -> gate the balance sheet -> on fallback cut the income and cash-flow quarters off at the
    balance sheet that is used.

Two layers, so the rules are testable without I/O: `build_statement_view` is pure, `load_statement_view` is the cache read
(the same `get_or_fetch_earnings_aware` keys and limits every step already uses, so it adds no cache key and, on a warm
cache, no FMP call). `data_quality_flags` is a second pure function over the same rows: it lists the rules that currently
trip, structurally, for the display markers (and later Watch); it persists nothing and carries no UI wording.

The raw cached rows are never modified: a bad row stays cached as FMP served it; this decides what to *use*."""

from dataclasses import dataclass
from datetime import date
from typing import Literal, NamedTuple

from sqlmodel import Session

from clients.fmp_client import fmp_client
from core.cache import get_or_fetch_earnings_aware, safe_fetch
from core.schemas import BalanceSheetFallback, DataQualityFlag
from helpers import statement_recheck as sr
from helpers.balance_sheet_gate import (
    DEBT_BASIS_SHORT_PLUS_LONG,
    DEBT_BASIS_TOTAL_DEBT,
    BalanceSheetSelection,
    align_quarters_to_balance_sheet,
    select_complete_balance_sheet,
)
from helpers.debt_metrics import DebtMetrics, compute_debt_metrics
from helpers.ttm import (
    TOTAL_QUARTERS_NEEDED,
    TTMResult,
    _period_net_income,
    clean_cash_flow_statements,
    is_placeholder_cash_flow_row,
    scale_break_evidence,
    sum_last_four_quarters,
)

# Annual window every step fetches (same cache key/limit as Step 1/3/4/5 and the Financials tab).
ANNUAL_WINDOW = 10
REIT_COMPANY_TYPE = "REIT/Property Developer"

# Rule names as they appear on a DataQualityFlag. The two balance-sheet gate rules fold into one; the gate's own reason
# (debt_remap / current_assets_remap) is `detail["reason"]`.
PLACEHOLDER_CF = "placeholder_cf"
SCALE_BREAK = "scale_break"
PARTIAL_BALANCE_SHEET = "partial_balance_sheet"
NOT_LANDED = "not_landed"


class RawStatements(NamedTuple):
    """One ticker's cached statement rows exactly as FMP served them, each list most-recent-first. A statement that was not
    loaded is an empty list."""

    income_annual: list[dict] = []
    income_quarterly: list[dict] = []
    cash_flow_annual: list[dict] = []
    cash_flow_quarterly: list[dict] = []
    balance_sheet_annual: list[dict] = []
    balance_sheet_quarterly: list[dict] = []


class UsedPeriods(NamedTuple):
    """Period ends of the rows the view actually uses: the balance sheet, and the newest quarter of the income and
    cash-flow TTM windows (a placeholder newest cash-flow quarter makes the cash-flow one older than the income one)."""

    balance_sheet: str | None
    income_ttm_end: str | None
    cash_flow_ttm_end: str | None


def debt_basis_for(company_type: str | None) -> str:
    """The "total debt" the gate watches: the one the scored path reads (REIT gearing: FMP's totalDebt; otherwise short +
    long term debt)."""
    return DEBT_BASIS_TOTAL_DEBT if company_type == REIT_COMPANY_TYPE else DEBT_BASIS_SHORT_PLUS_LONG


@dataclass(frozen=True)
class StatementView:
    raw: RawStatements  # the rows as cached, before any cleaning or alignment
    company_type: str | None
    debt_basis: str
    income_annual: list[dict]  # untouched
    income_quarterly: list[dict]  # aligned to the balance sheet used
    cash_flow_annual: list[dict]  # placeholder / scale-break rows blanked in place
    cash_flow_quarterly: list[dict]  # leading invalid run dropped, then aligned to the balance sheet used
    balance_sheet_annual: list[dict]  # raw: the annual balance-sheet series are not gated
    balance_sheet_quarterly: list[dict]  # raw list
    balance_sheet_row: dict  # the gated row ({} when there is no balance sheet)
    selection: BalanceSheetSelection
    balance_sheet_fallback: BalanceSheetFallback | None  # exactly what Step5Out.balance_sheet_fallback carries
    used: UsedPeriods
    debt_metrics: DebtMetrics  # compute_debt_metrics(balance_sheet_row, income_quarterly, income_annual)

    def ttm(self, statement: Literal["income", "cash_flow"], line: str) -> TTMResult:
        """Trailing four quarters of `line` over the cleaned, aligned quarters, with the matching annual rows for the
        Defect-B correction."""
        if statement == "income":
            return sum_last_four_quarters(self.income_quarterly, line, self.income_annual)
        return sum_last_four_quarters(self.cash_flow_quarterly, line, self.cash_flow_annual)


def build_statement_view(raw: RawStatements, company_type: str | None, *, use_balance_sheet: bool = True) -> StatementView:
    """Pure. `use_balance_sheet=False` (Step 1 reads no balance sheet): no gate, no alignment, `balance_sheet_row == {}`."""
    basis = debt_basis_for(company_type)
    is_reit = company_type == REIT_COMPANY_TYPE
    cash_flow_annual, cash_flow_quarterly = clean_cash_flow_statements(
        raw.cash_flow_annual, raw.cash_flow_quarterly, raw.income_annual, raw.income_quarterly
    )
    income_quarterly = raw.income_quarterly

    if use_balance_sheet:
        selection = select_complete_balance_sheet(raw.balance_sheet_quarterly, basis, check_current_assets=not is_reit)
    else:
        selection = BalanceSheetSelection({}, None, None, None, None)
    balance_sheet_fallback = None
    if selection.fallback_used:
        income_quarterly = align_quarters_to_balance_sheet(income_quarterly, selection.used_date)
        cash_flow_quarterly = align_quarters_to_balance_sheet(cash_flow_quarterly, selection.used_date)
        balance_sheet_fallback = BalanceSheetFallback(
            reason=selection.reason,
            incomplete_quarter_date=selection.incomplete_date,
            used_quarter_date=selection.used_date,
            detail=selection.detail,
        )

    return StatementView(
        raw=raw,
        company_type=company_type,
        debt_basis=basis,
        income_annual=raw.income_annual,
        income_quarterly=income_quarterly,
        cash_flow_annual=cash_flow_annual,
        cash_flow_quarterly=cash_flow_quarterly,
        balance_sheet_annual=raw.balance_sheet_annual,
        balance_sheet_quarterly=raw.balance_sheet_quarterly,
        balance_sheet_row=selection.row,
        selection=selection,
        balance_sheet_fallback=balance_sheet_fallback,
        used=UsedPeriods(
            balance_sheet=selection.used_date or (selection.row.get("date") if selection.row else None),
            income_ttm_end=income_quarterly[0].get("date") if income_quarterly else None,
            cash_flow_ttm_end=cash_flow_quarterly[0].get("date") if cash_flow_quarterly else None,
        ),
        debt_metrics=compute_debt_metrics(selection.row, income_quarterly, raw.income_annual),
    )


async def _rows(
    session: Session,
    ticker: str,
    statement_type: str,
    period: str,
    fetch,
    staleness_days: int,
    most_recent_earnings_date: date | None,
    cache_only: bool,
) -> list[dict]:
    data = await safe_fetch(
        f"{statement_type}_{period}",
        get_or_fetch_earnings_aware(
            session, ticker, statement_type, period, fetch, staleness_days, most_recent_earnings_date, cache_only
        ),
    )
    return data if isinstance(data, list) else []


async def load_statement_view(
    session: Session,
    ticker: str,
    company_type: str | None,
    *,
    most_recent_earnings_date: date | None,
    staleness_days: int,
    cache_only: bool,
    income: bool = True,
    cash_flow: bool = True,
    balance_sheet: bool = True,
    annual_balance_sheet: bool = False,
    balance_sheet_quarterly_rows: list[dict] | None = None,
) -> StatementView:
    """Fetch (cache first, the production earnings-aware rule) and build. Same cache keys and limits as every step:
    annual `ANNUAL_WINDOW`, quarterly `TOTAL_QUARTERS_NEEDED`. A statement left off by its flag is an empty list.
    `balance_sheet_quarterly_rows`: a caller that already fetched the quarterly balance sheet passes it instead of a second
    read."""

    def get(statement_type: str, period: str, call):
        return _rows(session, ticker, statement_type, period, call, staleness_days, most_recent_earnings_date, cache_only)

    income_annual = income_quarterly = cash_flow_annual = cash_flow_quarterly = []
    balance_sheet_annual = balance_sheet_quarterly = []
    if income:
        income_annual = await get("income_statement", "annual", lambda: fmp_client.get_income_statement(ticker, "annual", ANNUAL_WINDOW))
        income_quarterly = await get(
            "income_statement", "quarterly", lambda: fmp_client.get_income_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED)
        )
    if cash_flow:
        cash_flow_annual = await get(
            "cash_flow_statement", "annual", lambda: fmp_client.get_cash_flow_statement(ticker, "annual", ANNUAL_WINDOW)
        )
        cash_flow_quarterly = await get(
            "cash_flow_statement", "quarterly", lambda: fmp_client.get_cash_flow_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED)
        )
    if balance_sheet_quarterly_rows is not None:
        balance_sheet_quarterly = balance_sheet_quarterly_rows
    elif balance_sheet:
        balance_sheet_quarterly = await get(
            "balance_sheet_statement",
            "quarterly",
            lambda: fmp_client.get_balance_sheet_statement(ticker, "quarter", TOTAL_QUARTERS_NEEDED),
        )
    if annual_balance_sheet:
        balance_sheet_annual = await get(
            "balance_sheet_statement", "annual", lambda: fmp_client.get_balance_sheet_statement(ticker, "annual", ANNUAL_WINDOW)
        )
    raw = RawStatements(
        income_annual, income_quarterly, cash_flow_annual, cash_flow_quarterly, balance_sheet_annual, balance_sheet_quarterly
    )
    return build_statement_view(raw, company_type, use_balance_sheet=balance_sheet)


# --- data quality ------------------------------------------------------------------------------------------------------

_RAW_TTM_QUARTERS = 4  # the Financials tab's TTM column sums the four newest RAW quarters


def _date_of(row: dict) -> str | None:
    value = row.get("date")
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def _cash_flow_flags(raw: RawStatements) -> list[DataQualityFlag]:
    flags: list[DataQualityFlag] = []
    scale_broken_years: set[str] = set()
    for period, rows, income in (
        ("annual", raw.cash_flow_annual, raw.income_annual),
        ("quarterly", raw.cash_flow_quarterly, raw.income_quarterly),
    ):
        for index, row in enumerate(rows):
            in_ttm = period == "quarterly" and index < _RAW_TTM_QUARTERS
            if is_placeholder_cash_flow_row(row, income):
                net_income = _period_net_income(row, income)
                flags.append(
                    DataQualityFlag(
                        rule=PLACEHOLDER_CF,
                        statement="cash_flow",
                        period=period,
                        period_end=_date_of(row),
                        evidence=f"all cash-flow section totals are 0 while net income is {net_income:,.0f}",
                        detail={"net_income": net_income, "in_ttm_window": in_ttm},
                    )
                )
                continue
            evidence = scale_break_evidence(rows, index)
            if evidence is not None:
                lines, log_ratio = evidence
                if period == "annual" and row.get("fiscalYear") is not None:
                    scale_broken_years.add(row["fiscalYear"])
                flags.append(
                    DataQualityFlag(
                        rule=SCALE_BREAK,
                        statement="cash_flow",
                        period=period,
                        period_end=_date_of(row),
                        evidence=f"{lines} lines are about {10 ** abs(log_ratio):,.0f} times {'larger' if log_ratio > 0 else 'smaller'} than the neighbouring rows",
                        detail={"lines": lines, "log10_ratio": round(log_ratio, 2), "derived_q4": False, "in_ttm_window": in_ttm},
                    )
                )
    # The Q4 of a fiscal year whose annual row is a scale break is FMP's annual-minus-three-quarters: poisoned, and treated as
    # missing by clean_cash_flow_statements, so it is reported too (unless it tripped a rule on its own).
    flagged_quarters = {f.period_end for f in flags if f.period == "quarterly"}
    for index, row in enumerate(raw.cash_flow_quarterly):
        if row.get("period") == "Q4" and row.get("fiscalYear") in scale_broken_years and _date_of(row) not in flagged_quarters:
            flags.append(
                DataQualityFlag(
                    rule=SCALE_BREAK,
                    statement="cash_flow",
                    period="quarterly",
                    period_end=_date_of(row),
                    evidence=f"Q4 {row.get('fiscalYear')} is derived from a scale-broken annual row",
                    detail={"derived_q4": True, "in_ttm_window": index < _RAW_TTM_QUARTERS},
                )
            )
    return flags


def data_quality_flags(
    raw: RawStatements, earnings: list[dict], company_type: str | None, today: date | None = None
) -> list[DataQualityFlag]:
    """The read-time rules that currently trip on this ticker's cached rows, as structured flags. Pure: persists nothing,
    reads no cache, makes no call. Reuses `is_placeholder_cash_flow_row`, `scale_break_evidence`,
    `select_complete_balance_sheet` and the recheck's `not_landed_flag` as they are.

    placeholder_cf / scale_break: every annual and quarterly cash-flow row (a scale-broken year's derived Q4 included).
    partial_balance_sheet: the newest quarter, when the completeness gate would fall back. not_landed: the newest reported
    quarter has not reached the statements. A healed row simply stops producing its flag."""
    today = today or date.today()
    flags = _cash_flow_flags(raw)

    if raw.balance_sheet_quarterly:
        selection = select_complete_balance_sheet(
            raw.balance_sheet_quarterly, debt_basis_for(company_type), check_current_assets=company_type != REIT_COMPANY_TYPE
        )
        if selection.fallback_used:
            flags.append(
                DataQualityFlag(
                    rule=PARTIAL_BALANCE_SHEET,
                    statement="balance_sheet",
                    period="quarterly",
                    period_end=selection.incomplete_date,
                    evidence=selection.detail or "",
                    detail={
                        "reason": selection.reason,
                        "incomplete_quarter_date": selection.incomplete_date,
                        "used_quarter_date": selection.used_date,
                        "in_ttm_window": True,
                    },
                )
            )

    landed = sr.not_landed_flag(
        sr.Statements(
            raw.income_quarterly, raw.balance_sheet_quarterly, raw.cash_flow_quarterly, raw.cash_flow_annual, earnings
        ),
        today,
    )
    if landed is not None:
        newest = _date_of(raw.income_quarterly[0]) if raw.income_quarterly else None
        flags.append(
            DataQualityFlag(
                rule=NOT_LANDED,
                statement="income",
                period="quarterly",
                period_end=newest,
                evidence=f"earnings reported {landed.anchor.isoformat()}; newest income period ends {newest}",
                detail={"reported_on": landed.anchor.isoformat(), "in_ttm_window": False},
            )
        )
    return flags
