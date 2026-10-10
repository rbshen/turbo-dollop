"""Cache-only data-quality checks on FMP statement rows (docs/specs/data-quality.md). Pure: rows in, flags out, no I/O.

Three checks, all informational and feeding nothing (no score, verdict, label or TickerScore column):

  zero_newest_capex         the newest annual row has no capex while the prior years do (FCF = CFO then overstates)
  sbc_gap                   stock-based compensation is 0 in a year between non-zero years, or in the newest year
  net_income_disagreement   income-statement and cash-flow-statement net income differ for the same fiscal year

Rows are most-recent-first lists of FMP dicts. The cash-flow rows are expected CLEANED (`helpers/ttm.clean_cash_flow_statements`):
a placeholder or scale-broken row arrives blanked (CFO None) and is skipped here, because those already have their own markers
(docs/specs/statement-data-quality.md). Fiscal years are the cached annual rows; FMP serves only completed years.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

CHECK_ZERO_CAPEX = "zero_newest_capex"
CHECK_SBC_GAP = "sbc_gap"
CHECK_NET_INCOME = "net_income_disagreement"
CHECKS = (CHECK_ZERO_CAPEX, CHECK_SBC_GAP, CHECK_NET_INCOME)

KIND_ZERO_LINE = "zero_line"
KIND_ZERO_BETWEEN = "zero_between"
KIND_ZERO_NEWEST = "zero_newest"
KIND_SIGN_DIFFERS = "sign_differs"
KIND_LARGE_GAP = "large_gap"
KIND_DEFINITION = "definition"

# Company types whose FCF Step 1 does not score and whose capex line is not comparable (docs/specs/financials.md).
CAPEX_EXEMPT_TYPES = frozenset({"Bank", "Insurance", "REIT/Property Developer"})

# --- thresholds (chosen on the cached universe, see the spec's "Tuning" section) ------------------------------------------------
CAPEX_MIN_PRIOR_YEARS = 2  # prior fiscal years with a non-zero capex line
CAPEX_PRIOR_WINDOW = 3  # prior years looked at
CAPEX_MATERIALITY_OF_REVENUE = 0.005  # the prior years' median capex must be at least this share of the newest revenue
QUARTER_WINDOW_TOLERANCE_DAYS = 10
SBC_WINDOW_YEARS = 5
NI_RELATIVE_GAP = 0.25  # |cash-flow NI - income-statement NI| / the larger of the two
NI_MATERIALITY_OF_REVENUE = 0.01  # and the gap must be at least this share of revenue
NI_DEFINITION_MIN_YEARS = 3  # the same-direction disagreement in this many years is a definition effect
NI_SCAN_YEARS = 3  # a data-error flag is raised for the newest this-many fiscal years only
NI_CONTINUING_TOLERANCE = 0.02


@dataclass(frozen=True)
class QualityFlag:
    ticker: str
    check: str
    field: str
    fiscal_year: str
    fmp_value: float | None
    comparison_value: float | None
    kind: str
    detail: str


@dataclass(frozen=True)
class SbcZeroYears:
    """Zero (or missing) stock-based-compensation years among the last `window` fiscal years the cache holds. The stuck-check card
    reads it for its note on rows 2-3."""

    zero_years: int
    window: int
    fiscal_years: tuple[str, ...]


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _fy(row: dict) -> str:
    return str(row.get("fiscalYear") or (row.get("date") or "")[:4])


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


def _usable(rows: list[dict]) -> list[dict]:
    """Cash-flow rows that carry data: the cleaner blanks a placeholder or scale-broken row (CFO None)."""
    return [r for r in rows if _num(r.get("netCashProvidedByOperatingActivities")) is not None]


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    a = abs(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= limit:
            return f"{sign}${a / limit:,.1f}{suffix}"
    return f"{sign}${a:,.0f}"


# --- 1. zero newest capex -------------------------------------------------------------------------------------------------------


def check_zero_newest_capex(
    ticker: str,
    company_type: str | None,
    cash_flow_annual: list[dict],
    cash_flow_quarterly: list[dict],
    income_annual: list[dict],
) -> list[QualityFlag]:
    """The newest annual cash-flow row has capex 0 or missing, the prior fiscal years carry a non-zero capex line, and the quarterly
    rows of that fiscal year (where cached) show capex. FMP sometimes drops the PP&E line from a freshly closed year, so free cash
    flow (CFO + capex) reads as CFO (MU, CSCO, SYY, STX FY2026). Not for Bank / Insurance / REIT / Property Developer."""
    if company_type in CAPEX_EXEMPT_TYPES:
        return []
    rows = _usable(cash_flow_annual)
    if len(rows) < 1 + CAPEX_MIN_PRIOR_YEARS:
        return []
    newest, prior = rows[0], rows[1 : 1 + CAPEX_PRIOR_WINDOW]
    capex = _num(newest.get("capitalExpenditure")) or 0.0
    cfo = _num(newest.get("netCashProvidedByOperatingActivities")) or 0.0
    if capex != 0 or cfo == 0:
        return []
    prior_capex = [abs(_num(r.get("capitalExpenditure")) or 0.0) for r in prior]
    nonzero = [c for c in prior_capex if c > 0]
    if len(nonzero) < CAPEX_MIN_PRIOR_YEARS or len(nonzero) * 2 <= len(prior_capex):
        return []
    revenue = abs(_num(next((r.get("revenue") for r in income_annual if r.get("date") == newest.get("date")), None)) or 0.0)
    if revenue and median(prior_capex) < CAPEX_MATERIALITY_OF_REVENUE * revenue:
        return []

    end, prior_end = _date(newest.get("date")), _date(prior[0].get("date"))
    quarters = []
    if end and prior_end:
        lo, hi = prior_end + timedelta(days=QUARTER_WINDOW_TOLERANCE_DAYS), end + timedelta(days=QUARTER_WINDOW_TOLERANCE_DAYS)
        quarters = [q for q in _usable(cash_flow_quarterly) if (d := _date(q.get("date"))) and lo < d <= hi]
    quarter_capex = [_num(q.get("capitalExpenditure")) or 0.0 for q in quarters]
    fy = _fy(newest)
    if quarters and not any(quarter_capex):
        return []  # the quarters agree with the annual zero
    comparison = _num(prior[0].get("capitalExpenditure"))
    if quarters:
        # The quarterly rows are no figure to quote: FMP derives a fiscal-year Q4 from the annual row, so a zero annual line bends them.
        detail = (
            f"FY{fy} capex is 0 in the newest annual row, but its quarterly rows report capex (FY{_fy(prior[0])} was {_money(comparison)}), "
            "so free cash flow may be overstated."
        )
    else:
        detail = f"FY{fy} capex is 0 in the newest row after {_money(comparison)} the year before, so free cash flow may be overstated."
    return [QualityFlag(ticker, CHECK_ZERO_CAPEX, "capitalExpenditure", fy, 0.0, comparison, KIND_ZERO_LINE, detail)]


# --- 2. stock-based compensation gap --------------------------------------------------------------------------------------------


def _sbc_by_year(cash_flow_annual: list[dict]) -> list[tuple[str, float]]:
    """Chronological (oldest first) (fiscal year, SBC) for the usable annual rows; a missing value counts as 0."""
    return [(_fy(r), abs(_num(r.get("stockBasedCompensation")) or 0.0)) for r in reversed(_usable(cash_flow_annual))]


def sbc_zero_years(cash_flow_annual: list[dict], window: int = SBC_WINDOW_YEARS) -> SbcZeroYears:
    years = _sbc_by_year(cash_flow_annual)[-window:]
    zero = tuple(fy for fy, value in years if value == 0)
    return SbcZeroYears(zero_years=len(zero), window=len(years), fiscal_years=zero)


def check_sbc_gap(ticker: str, cash_flow_annual: list[dict]) -> list[QualityFlag]:
    """SBC is 0 in a fiscal year that sits between non-zero years, or in the newest year after non-zero years. A company that never
    reports SBC, or whose early years are 0 before the first non-zero one, is not flagged here (the stuck-check card handles an
    all-zero history with its own Not reported rule). Looks at the last five fiscal years."""
    years = _sbc_by_year(cash_flow_annual)[-SBC_WINDOW_YEARS:]
    flags = []
    for i, (fy, value) in enumerate(years):
        if value != 0:
            continue
        before = [v for _, v in years[:i] if v > 0]
        after = [v for _, v in years[i + 1 :] if v > 0]
        if before and after:
            kind = KIND_ZERO_BETWEEN
            neighbour = next(v for _, v in reversed(years[:i]) if v > 0)
            detail = f"Stock-based compensation reads 0 for FY{fy} between non-zero years, so SBC totals may be understated."
        elif before and i == len(years) - 1:
            kind = KIND_ZERO_NEWEST
            neighbour = next(v for _, v in reversed(years[:i]) if v > 0)
            detail = f"Stock-based compensation reads 0 for the newest year, FY{fy}, after non-zero years, so it may be missing."
        else:
            continue
        flags.append(QualityFlag(ticker, CHECK_SBC_GAP, "stockBasedCompensation", fy, 0.0, neighbour, kind, detail))
    return flags


# --- 3. net income disagreement -------------------------------------------------------------------------------------------------


def _ni_pairs(income_annual: list[dict], cash_flow_annual: list[dict]) -> list[tuple[str, float, float, float, float | None]]:
    """Newest first: (fiscal year, income-statement NI, cash-flow NI, revenue, income-statement NI from continuing operations)
    for the years both statements carry."""
    cash_by_date = {r.get("date"): r for r in _usable(cash_flow_annual)}
    pairs = []
    for row in income_annual:
        cash = cash_by_date.get(row.get("date"))
        income_ni, cash_ni = _num(row.get("netIncome")), _num(cash.get("netIncome")) if cash else None
        if income_ni is None or cash_ni is None:
            continue
        pairs.append(
            (_fy(row), income_ni, cash_ni, abs(_num(row.get("revenue")) or 0.0), _num(row.get("netIncomeFromContinuingOperations")))
        )
    return pairs


def _disagrees(income_ni: float, cash_ni: float, revenue: float) -> str | None:
    gap = abs(cash_ni - income_ni)
    if revenue <= 0 or gap < NI_MATERIALITY_OF_REVENUE * revenue:
        return None
    if income_ni * cash_ni < 0:
        return KIND_SIGN_DIFFERS
    if gap / max(abs(income_ni), abs(cash_ni)) > NI_RELATIVE_GAP:
        return KIND_LARGE_GAP
    return None


def _matches_continuing(cash_ni: float, continuing: float | None) -> bool:
    return continuing is not None and abs(cash_ni - continuing) <= max(NI_CONTINUING_TOLERANCE * abs(continuing), 1e6)


def check_net_income_disagreement(ticker: str, income_annual: list[dict], cash_flow_annual: list[dict]) -> list[QualityFlag]:
    """Income-statement vs cash-flow-statement net income for the same fiscal year. FMP's income statement carries the share
    attributable to the parent and, after discontinued operations, bottom-line income; its cash-flow statement starts from
    consolidated income from continuing operations (IBKR: 984 vs 4,357 in FY2025; JNJ FY2023: 35,153 vs 13,326). A year where the
    cash-flow figure equals the income statement's own `netIncomeFromContinuingOperations`, or where the cash-flow figure is the
    larger in 3 or more of the last five years, is a definition effect: one `definition` flag for the newest such year. Any other
    disagreement in the newest three years is a probable data error (WTW FY2024: 1,248 vs -98)."""
    pairs = _ni_pairs(income_annual, cash_flow_annual)[:SBC_WINDOW_YEARS]
    verdicts = [(p, _disagrees(p[1], p[2], p[3])) for p in pairs]
    higher = [p for p, kind in verdicts if kind and p[2] > p[1]]
    persistent = len(higher) >= NI_DEFINITION_MIN_YEARS
    flags: list[QualityFlag] = []
    definition: tuple[str, float, float] | None = None
    for (fy, income_ni, cash_ni, _revenue, continuing), kind in verdicts:
        if not kind:
            continue
        if _matches_continuing(cash_ni, continuing) or persistent and cash_ni > income_ni:
            if definition is None:
                definition = (fy, income_ni, cash_ni)
            continue
    for (fy, income_ni, cash_ni, _revenue, continuing), kind in verdicts[:NI_SCAN_YEARS]:
        if not kind or _matches_continuing(cash_ni, continuing) or persistent and cash_ni > income_ni:
            continue
        what = "opposite signs" if kind == KIND_SIGN_DIFFERS else "very different figures"
        detail = (
            f"FY{fy} net income is {_money(income_ni)} on the income statement but {_money(cash_ni)} on the cash-flow statement "
            f"({what}); one of them may be wrong."
        )
        flags.append(QualityFlag(ticker, CHECK_NET_INCOME, "netIncome", fy, income_ni, cash_ni, kind, detail))
    if definition is not None:
        fy, income_ni, cash_ni = definition
        detail = (
            f"FY{fy} income-statement net income ({_money(income_ni)}) is the parent's bottom line; the cash-flow statement starts "
            f"from consolidated income from continuing operations ({_money(cash_ni)}). A definition difference, not an error."
        )
        flags.insert(0, QualityFlag(ticker, CHECK_NET_INCOME, "netIncome", fy, income_ni, cash_ni, KIND_DEFINITION, detail))
    return flags


# --- all checks ------------------------------------------------------------------------------------------------------------------


def run_checks(
    ticker: str,
    company_type: str | None,
    income_annual: list[dict],
    cash_flow_annual: list[dict],
    cash_flow_quarterly: list[dict],
) -> list[QualityFlag]:
    """Every check over one ticker's (cleaned) cached rows, in a stable order."""
    return [
        *check_zero_newest_capex(ticker, company_type, cash_flow_annual, cash_flow_quarterly, income_annual),
        *check_sbc_gap(ticker, cash_flow_annual),
        *check_net_income_disagreement(ticker, income_annual, cash_flow_annual),
    ]
