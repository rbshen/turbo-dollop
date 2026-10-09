"""The "Why might it be stuck?" card: pure scoring/labelling functions (no I/O). docs/specs/stuck-check.md.

Informational only: nothing here feeds Overall, a verdict, TickerScore or the Screener. A row carries a figure set and, for the four
labelled rows (cash conversion, SBC, FCF after SBC, share count), one of OK / Flagged / Not applicable / Not reported; every other
row is figures only (status None). "Flagged" is a plain tag: never a verdict word, never red.

The split mirrors scoring/speculative_growth.py: this module takes plain per-fiscal-year numbers (`FiscalYear`, chronological, oldest
first, completed fiscal years only) and the thresholds (`StuckSettings`), and returns `StuckRow`s. data/stuck_check_data.py assembles
the inputs from the cleaned cached statements and the stored price values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

OK = "ok"
FLAGGED = "flagged"
NOT_APPLICABLE = "not_applicable"
NOT_REPORTED = "not_reported"

SUBTITLE = "Context, not scored"

# Row keys an exemption entry may name (a ticker-level exemption, Settings > Why might it be stuck?). Rows 7 and 8 read stored
# values and are not exemptable. "2_fcf" is the %-of-FCF half of the SBC row.
EXEMPTABLE_ROW_LABELS: dict[str, str] = {
    "1": "Cash conversion",
    "2": "Stock-based compensation",
    "2_fcf": "SBC as % of free cash flow",
    "3": "FCF after stock-based compensation",
    "4": "Buybacks vs stock-based compensation",
    "5": "Share count",
    "6": "Shareholder yield",
    "9": "Margins",
    "10": "Growth",
    "12": "Return on invested capital",
}
EXEMPTABLE_ROWS: tuple[str, ...] = tuple(EXEMPTABLE_ROW_LABELS)

# Company types whose FCF is not comparable to a Standard company's (Step 1 exempts CFO and FCF for Bank / Insurance / REIT; a
# Utility's FCF is structurally negative, docs/why-stuck-panel-investigation-2026-10-09.md). Cash conversion (1) and FCF after SBC
# (3) are Not applicable for them, and the %-of-FCF half of the SBC row is not assessed (the investigation's matrix: "% rev only").
FCF_EXEMPT_TYPES = frozenset({"Bank", "Insurance", "REIT/Property Developer", "Utility"})
# Issuance is the model: the share-count row shows the figure with no label.
SHARE_COUNT_NEUTRAL_TYPES = frozenset({"REIT/Property Developer", "Utility"})
ROIC_STANDARD_ONLY = "Standard"

# Fixed rules that stay in code (the spec's list of what is not a setting).
CASH_CONVERSION_SHORT_YEARS = 3
CASH_CONVERSION_LONG_YEARS = 10
NET_INCOME_FLOOR_PCT_OF_REVENUE = 2.0
SBC_WINDOW_YEARS = 5
SBC_NOT_REPORTED_MIN_ZERO_YEARS = 3
MIN_LABELLED_YEARS = 3  # a labelled window needs at least this many post-listing fiscal years
BUYBACK_SBC_GATE_PCT_OF_REVENUE = 5.0
SHARE_WINDOW_POINTS = 6  # 6 fiscal years = a 5-year CAGR
WEIGHT_NOTE_PCT_OF_SECTOR = 10.0
COVID_BASE_DROP_PCT = 15.0
COVID_FYE_FROM = date(2020, 3, 1)
COVID_FYE_TO = date(2021, 3, 31)
GROSS_MARGIN_UNRELIABLE_AT_PCT = 99.0  # FMP gross profit ~= revenue: financials.md, "Known weaknesses"
MARGIN_YEARS = 5
GROWTH_YEARS = 5
MIN_SECTOR_PEERS = 5
RELATIVE_STRENGTH_WINDOWS = (1, 3, 6, 12)  # months
_FY_LENGTH_LESS_A_DAY = timedelta(days=364)  # a fiscal year began this long before its period end


@dataclass(frozen=True)
class Exemption:
    ticker: str
    reason: str
    rows: tuple[str, ...]


@dataclass(frozen=True)
class StuckSettings:
    """The editable thresholds (Settings > Why might it be stuck?). The defaults are the code's; the saved set can differ."""

    sbc_revenue_pct: float = 8.0
    sbc_fcf_pct: float = 30.0
    cash_conversion_line: float = 0.7
    share_growth_pct: float = 2.0
    one_off_pct: float = 60.0
    sector_band_pp: float = 2.0
    smoothing_days: int = 5
    exemptions: tuple[Exemption, ...] = (
        Exemption("IBKR", "Broker: customer cash and segregated funds distort cash flow, and the Up-C share structure inflates the diluted count", ("1", "2_fcf", "3", "5", "6")),
        Exemption("GM", "Captive finance arm: financing receivables run through operating cash flow", ("1", "3", "6")),
    )


DEFAULT_STUCK_SETTINGS = StuckSettings()

# (min, max) per numeric setting, inclusive.
STUCK_BOUNDS: dict[str, tuple[float, float]] = {
    "sbc_revenue_pct": (1.0, 50.0),
    "sbc_fcf_pct": (5.0, 100.0),
    "cash_conversion_line": (0.1, 1.5),
    "share_growth_pct": (0.5, 10.0),
    "one_off_pct": (30.0, 95.0),
    "sector_band_pp": (0.5, 10.0),
    "smoothing_days": (1, 20),
}


@dataclass(frozen=True)
class FiscalYear:
    """One completed fiscal year, all in reporting-currency units (`roic_pct` in percent). None = missing/blanked by the cleaned loader.
    `buybacks` and `dividends` are positive outflows; `net_buybacks` is positive for net repurchases, negative for net issuance."""

    fiscal_year: str
    period_end: date | None = None
    revenue: float | None = None
    net_income: float | None = None
    operating_income: float | None = None
    gross_profit: float | None = None
    fcf: float | None = None
    sbc: float | None = None
    buybacks: float | None = None
    net_buybacks: float | None = None
    dividends: float | None = None
    diluted_shares: float | None = None
    roic_pct: float | None = None


@dataclass
class Figure:
    key: str
    label: str
    value: float | None
    unit: str  # usd | pct | pp | ratio | multiple | count | text
    text: str | None = None  # a word that replaces or accompanies the value ("n/m", "in line", "93rd percentile")


@dataclass
class StuckRow:
    key: str
    number: int
    title: str
    status: str | None
    reason: str | None = None
    figures: list[Figure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class StuckResult:
    rows: list[StuckRow]
    footer: str | None


# --- small helpers -----------------------------------------------------------------------------------------------------------


def _has(value: float | None) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def _sum(values: list[float | None]) -> float:
    return sum(v for v in values if _has(v))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _slope(values: list[float]) -> float:
    """Least-squares slope per step (here: per fiscal year) of an evenly spaced series."""
    n = len(values)
    xs = range(n)
    mean_x, mean_y = (n - 1) / 2, _mean(values)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denominator if denominator else 0.0


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _fy_number(fy: FiscalYear) -> int | None:
    try:
        return int(fy.fiscal_year)
    except (TypeError, ValueError):
        return fy.period_end.year if fy.period_end else None


def post_listing_years(years: list[FiscalYear], ipo_date: date | None) -> list[FiscalYear]:
    """Fiscal years that began on or after the listing date (the first FULL fiscal year after the IPO onward). No listing date (or a
    year with no period end and no usable fiscal-year number) keeps the year, so an unknown date never shrinks a window."""
    if ipo_date is None:
        return list(years)
    kept = []
    for fy in years:
        if fy.period_end is not None:
            if fy.period_end - _FY_LENGTH_LESS_A_DAY >= ipo_date:
                kept.append(fy)
        else:
            number = _fy_number(fy)
            if number is None or number > ipo_date.year:
                kept.append(fy)
    return kept


# --- exemptions --------------------------------------------------------------------------------------------------------------


def exempt_rows(ticker: str, company_type: str | None, settings: StuckSettings) -> dict[str, str]:
    """row key -> reason, from the company type and the hand-maintained ticker list."""
    exempt: dict[str, str] = {}
    if company_type in FCF_EXEMPT_TYPES:
        why = f"Free cash flow is not comparable for a {_TYPE_NOUN.get(company_type, company_type)}"
        exempt["1"] = why
        exempt["3"] = why
        exempt["2_fcf"] = why
    for entry in settings.exemptions:
        if entry.ticker.upper() == ticker.upper():
            for row in entry.rows:
                exempt[row] = entry.reason
    return exempt


_TYPE_NOUN = {"Bank": "bank", "Insurance": "insurer", "REIT/Property Developer": "REIT or property developer", "Utility": "utility"}


# --- row 1: cash conversion --------------------------------------------------------------------------------------------------


def _conversion(years: list[FiscalYear]) -> float | None:
    """Cumulative FCF / cumulative net income, None when net income is under 2% of revenue over the window (a ratio on a near-zero
    denominator is noise: DDOG 14.7, WDAY 32.3) or the window has no revenue."""
    revenue, net_income, fcf = _sum([y.revenue for y in years]), _sum([y.net_income for y in years]), _sum([y.fcf for y in years])
    if revenue <= 0 or net_income < revenue * NET_INCOME_FLOOR_PCT_OF_REVENUE / 100 or net_income <= 0:
        return None
    return fcf / net_income


def cash_conversion_row(years: list[FiscalYear], settings: StuckSettings, exempt: dict[str, str]) -> StuckRow:
    row = StuckRow("cash_conversion", 1, "Cash conversion", None)
    if "1" in exempt:
        row.status, row.reason = NOT_APPLICABLE, exempt["1"]
        return row
    usable = [y for y in years if _has(y.revenue) and _has(y.net_income) and _has(y.fcf)]
    if len(usable) < CASH_CONVERSION_SHORT_YEARS:
        row.status, row.reason = NOT_REPORTED, "Fewer than 3 fiscal years of cash flow"
        return row
    short = _conversion(usable[-CASH_CONVERSION_SHORT_YEARS:])
    long = _conversion(usable[-CASH_CONVERSION_LONG_YEARS:])
    row.figures = [Figure("last_3y", "Last 3 fiscal years", short, "ratio", None if short is not None else "n/m")]
    if len(usable) > CASH_CONVERSION_SHORT_YEARS:  # otherwise the long window IS the short one
        label = f"Last {min(len(usable), CASH_CONVERSION_LONG_YEARS)} fiscal years"
        row.figures.append(Figure("last_10y", label, long, "ratio", None if long is not None else "n/m"))
    if short is None:
        row.status, row.reason = NOT_APPLICABLE, "Net income is under 2% of revenue over the last 3 fiscal years"
        return row
    line = settings.cash_conversion_line
    # Flag only when BOTH windows sit below the line: a capex build-out shows in the last 3y but not the 10y (MSFT 0.66 / 0.82).
    row.status = FLAGGED if long is not None and short < line and long < line else OK
    return row


# --- rows 2-4: stock-based compensation --------------------------------------------------------------------------------------


def _pct(numerator: float, denominator: float) -> float | None:
    return numerator / denominator * 100 if denominator else None


def sbc_rows(
    window: list[FiscalYear], settings: StuckSettings, exempt: dict[str, str]
) -> tuple[StuckRow, StuckRow, StuckRow | None]:
    """Rows 2 (SBC), 3 (FCF after SBC) and 4 (buybacks vs SBC, None when it is not shown). `window` is the post-listing fiscal years."""
    sbc_row = StuckRow("sbc", 2, "Stock-based compensation", None)
    after_row = StuckRow("fcf_after_sbc", 3, "FCF after stock-based compensation", None)
    fcf_exempt_3 = "3" in exempt

    if "2" in exempt:
        sbc_row.status, sbc_row.reason = NOT_APPLICABLE, exempt["2"]
    if fcf_exempt_3:
        after_row.status, after_row.reason = NOT_APPLICABLE, exempt["3"]

    last5 = window[-SBC_WINDOW_YEARS:]
    if not last5:
        for r in (sbc_row, after_row):
            if r.status is None:
                r.status, r.reason = NOT_REPORTED, "No fiscal years since the listing"
        return sbc_row, after_row, None

    latest = last5[-1]
    short_window = len(window) < MIN_LABELLED_YEARS

    # Latest-FY figures: always shown when there is anything to show.
    def latest_figures() -> list[Figure]:
        figures = [Figure("sbc_latest", "Latest fiscal year", latest.sbc if _has(latest.sbc) else None, "usd")]
        if _has(latest.sbc) and _has(latest.revenue):
            figures.append(Figure("sbc_latest_pct_revenue", "Latest fiscal year, % of revenue", _pct(latest.sbc, latest.revenue), "pct"))
        return figures

    if short_window:
        note = f"Only {len(window)} fiscal year{'s' if len(window) != 1 else ''} since the listing: latest year shown, no label"
        if sbc_row.status is None:
            sbc_row.figures, sbc_row.notes = latest_figures(), [note]
        if after_row.status is None:
            fcf, sbc = latest.fcf, latest.sbc
            after_row.figures = [
                Figure("fcf_after_sbc_latest", "Latest fiscal year", fcf - sbc if _has(fcf) and _has(sbc) else None, "usd")
            ]
            if _has(fcf) and _has(sbc) and _has(latest.revenue):
                after_row.figures.append(
                    Figure("fcf_after_sbc_latest_pct_revenue", "Latest fiscal year, % of revenue", _pct(fcf - sbc, latest.revenue), "pct")
                )
            after_row.notes = [note]
        return sbc_row, after_row, None

    zero_years = sum(1 for y in last5 if not _has(y.sbc) or y.sbc == 0)
    if zero_years >= SBC_NOT_REPORTED_MIN_ZERO_YEARS:
        reason = f"Stock-based compensation is zero or missing in {zero_years} of the last {len(last5)} fiscal years"
        if sbc_row.status is None:
            sbc_row.status, sbc_row.reason = NOT_REPORTED, reason
        if after_row.status is None:
            after_row.status, after_row.reason = NOT_REPORTED, reason
        return sbc_row, after_row, None

    paired = [y for y in last5 if _has(y.sbc) and _has(y.revenue)]
    total_sbc = _sum([y.sbc for y in paired])
    total_revenue = _sum([y.revenue for y in paired])
    pct_revenue = _pct(total_sbc, total_revenue)

    if sbc_row.status is None:
        fcf_applicable = "2_fcf" not in exempt
        total_fcf = _sum([y.fcf for y in last5 if _has(y.sbc)])
        raw_pct_fcf = _pct(total_sbc, total_fcf) if total_fcf > 0 else None
        pct_fcf_nm = raw_pct_fcf is None or raw_pct_fcf > 100
        sbc_row.figures = latest_figures() + [
            Figure("sbc_5y_pct_revenue", f"{len(paired)}-year total, % of revenue", pct_revenue, "pct"),
        ]
        if fcf_applicable:
            sbc_row.figures.append(
                Figure("sbc_5y_pct_fcf", f"{len(last5)}-year total, % of free cash flow", None if pct_fcf_nm else raw_pct_fcf, "pct", "n/m" if pct_fcf_nm else None)
            )
        else:
            sbc_row.notes.append(f"% of free cash flow not assessed: {exempt['2_fcf']}")
        over_revenue = pct_revenue is not None and pct_revenue > settings.sbc_revenue_pct
        # n/m (FCF zero/negative, or the share above 100%) counts as exceeding the threshold.
        over_fcf = fcf_applicable and (pct_fcf_nm or raw_pct_fcf > settings.sbc_fcf_pct)
        sbc_row.status = FLAGGED if over_revenue or over_fcf else OK

    if after_row.status is None:
        fcf_sbc_pairs = [y for y in last5 if _has(y.fcf) and _has(y.sbc)]
        total_after = _sum([y.fcf - y.sbc for y in fcf_sbc_pairs])
        revenue_after = _sum([y.revenue for y in fcf_sbc_pairs if _has(y.revenue)])
        latest_pair = latest if _has(latest.fcf) and _has(latest.sbc) else None
        latest_after = latest_pair.fcf - latest_pair.sbc if latest_pair else None
        after_row.figures = [
            Figure("fcf_after_sbc_5y", f"{len(fcf_sbc_pairs)}-year total", total_after if fcf_sbc_pairs else None, "usd"),
            Figure("fcf_after_sbc_5y_pct_revenue", f"{len(fcf_sbc_pairs)}-year total, % of revenue", _pct(total_after, revenue_after) if fcf_sbc_pairs else None, "pct"),
            Figure("fcf_after_sbc_latest", "Latest fiscal year", latest_after, "usd"),
            Figure(
                "fcf_after_sbc_latest_pct_revenue",
                "Latest fiscal year, % of revenue",
                _pct(latest_after, latest.revenue) if latest_after is not None and _has(latest.revenue) else None,
                "pct",
            ),
        ]
        if not fcf_sbc_pairs:
            after_row.status, after_row.reason = NOT_REPORTED, "Free cash flow is missing"
        else:
            after_row.status = FLAGGED if total_after <= 0 or (latest_after is not None and latest_after < 0) else OK

    buyback_row = None
    if "4" not in exempt and pct_revenue is not None and pct_revenue >= BUYBACK_SBC_GATE_PCT_OF_REVENUE and sbc_row.status != NOT_APPLICABLE:
        total_buybacks = _sum([y.buybacks for y in last5])
        buyback_row = StuckRow("buybacks_vs_sbc", 4, "Buybacks vs stock-based compensation", None)
        if total_buybacks <= 0:
            buyback_row.figures = [Figure("buybacks_multiple", "Gross buybacks vs SBC", None, "text", "No buybacks")]
        else:
            buyback_row.figures = [Figure("buybacks_multiple", "Gross buybacks vs SBC", total_buybacks / total_sbc, "multiple")]
    return sbc_row, after_row, buyback_row


# --- row 5: share count ------------------------------------------------------------------------------------------------------


def share_count_row(
    window: list[FiscalYear], company_type: str | None, settings: StuckSettings, exempt: dict[str, str]
) -> StuckRow:
    row = StuckRow("share_count", 5, "Share count", None)
    if "5" in exempt:
        row.status, row.reason = NOT_APPLICABLE, exempt["5"]
        return row
    if len(window) < MIN_LABELLED_YEARS:
        row.status, row.reason = NOT_APPLICABLE, "Fewer than 3 fiscal years since the listing"
        return row
    points = [(y, y.diluted_shares) for y in window if _has(y.diluted_shares) and y.diluted_shares > 0][-SHARE_WINDOW_POINTS:]
    if len(points) < MIN_LABELLED_YEARS:
        row.status, row.reason = NOT_REPORTED, "Diluted share count is missing"
        return row
    first, last = points[0], points[-1]
    first_number, last_number = _fy_number(first[0]), _fy_number(last[0])
    span = (last_number - first_number) if first_number is not None and last_number is not None else len(points) - 1
    span = max(span, 1)
    cagr = (last[1] / first[1]) ** (1 / span) - 1
    row.figures = [Figure("share_cagr", f"Diluted shares, {span}-year change per year", cagr * 100, "pct")]

    steps = [math.log(points[i][1] / points[i - 1][1]) for i in range(1, len(points))]
    total = math.log(last[1] / first[1])
    biggest = max(range(len(steps)), key=lambda i: steps[i])
    one_off = total > 0 and steps[biggest] / total >= settings.one_off_pct / 100

    if company_type in SHARE_COUNT_NEUTRAL_TYPES:
        row.status = None
        row.notes.append("Issuance is the business model for this company type: figure shown, no label")
        return row
    if cagr * 100 > settings.share_growth_pct:
        if one_off:
            row.status = OK
            row.notes.append(
                f"One-off issuance in FY{points[biggest + 1][0].fiscal_year} carries {steps[biggest] / total * 100:.0f}% of the dilution"
            )
        else:
            row.status = FLAGGED
    else:
        row.status = OK
    return row


# --- row 6: shareholder yield ------------------------------------------------------------------------------------------------


def shareholder_yield_row(years: list[FiscalYear], exempt: dict[str, str]) -> StuckRow:
    row = StuckRow("shareholder_yield", 6, "Shareholder yield", None)
    if "6" in exempt:
        row.status, row.reason = NOT_APPLICABLE, exempt["6"]
        return row
    last5 = [y for y in years if _has(y.fcf)][-SBC_WINDOW_YEARS:]
    if len(last5) < MIN_LABELLED_YEARS:
        row.status, row.reason = NOT_REPORTED, "Fewer than 3 fiscal years of cash flow"
        return row
    paid = _sum([y.dividends for y in last5]) + _sum([y.net_buybacks for y in last5])
    fcf = _sum([y.fcf for y in last5])
    nm = fcf <= 0
    row.figures = [
        Figure("returned_5y", f"Dividends + net buybacks, {len(last5)} years", paid, "usd"),
        Figure("shareholder_yield_pct_fcf", f"% of {len(last5)}-year free cash flow", None if nm else paid / fcf * 100, "pct", "n/m" if nm else None),
    ]
    return row


# --- row 9: margins ----------------------------------------------------------------------------------------------------------


def _margin_figures(prefix: str, label: str, margins: list[float]) -> list[Figure]:
    return [
        Figure(f"{prefix}_first3", f"{label}, first 3 years average", _mean(margins[:3]), "pct"),
        Figure(f"{prefix}_last3", f"{label}, last 3 years average", _mean(margins[-3:]), "pct"),
        Figure(f"{prefix}_slope", f"{label}, trend per year", _slope(margins), "pp"),
    ]


def margins_row(years: list[FiscalYear], company_type: str | None, exempt: dict[str, str]) -> StuckRow:
    row = StuckRow("margins", 9, "Margins", None)
    if "9" in exempt:
        row.status, row.reason = NOT_APPLICABLE, exempt["9"]
        return row
    last = years[-MARGIN_YEARS:]
    if len(last) < MARGIN_YEARS or not all(_has(y.revenue) and y.revenue > 0 for y in last):
        row.status, row.reason = NOT_REPORTED, "Fewer than 5 fiscal years of revenue"
        return row
    if not all(_has(y.operating_income) for y in last):
        row.status, row.reason = NOT_REPORTED, "Operating income is missing"
        return row
    operating = [y.operating_income / y.revenue * 100 for y in last]
    row.figures = _margin_figures("operating_margin", "Operating margin", operating)
    if company_type == "Bank":
        row.notes.append("Gross margin not shown: FMP gross profit is not a real margin for banks")
    elif all(_has(y.gross_profit) for y in last):
        gross = [y.gross_profit / y.revenue * 100 for y in last]
        if _mean(gross[-3:]) >= GROSS_MARGIN_UNRELIABLE_AT_PCT:
            row.notes.append("Gross margin not shown: FMP reports about 100%, not a real goods margin")
        else:
            row.figures += _margin_figures("gross_margin", "Gross margin", gross)
    return row


# --- row 10: growth ----------------------------------------------------------------------------------------------------------


def revenue_cagr_pct(years: list[FiscalYear]) -> float | None:
    """5-year revenue CAGR over the last 6 fiscal years (None when fewer than 6 or a non-positive end point). Shared with the data
    module, which computes the same figure for the sector peers."""
    last = years[-(GROWTH_YEARS + 1):]
    if len(last) < GROWTH_YEARS + 1 or not _has(last[0].revenue) or not _has(last[-1].revenue):
        return None
    if last[0].revenue <= 0 or last[-1].revenue <= 0:
        return None
    return ((last[-1].revenue / last[0].revenue) ** (1 / GROWTH_YEARS) - 1) * 100


def growth_row(years: list[FiscalYear], sector_cagrs: list[float], exempt: dict[str, str]) -> StuckRow:
    row = StuckRow("growth", 10, "Growth", None)
    if "10" in exempt:
        row.status, row.reason = NOT_APPLICABLE, exempt["10"]
        return row
    cagr = revenue_cagr_pct(years)
    if cagr is None:
        row.status, row.reason = NOT_REPORTED, "Fewer than 6 fiscal years of revenue"
        return row
    row.figures = [Figure("revenue_cagr_5y", "Revenue growth, 5-year CAGR", cagr, "pct")]
    if len(sector_cagrs) >= MIN_SECTOR_PEERS:
        ordered = sorted(sector_cagrs)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        below = sum(1 for c in sector_cagrs if c < cagr)
        percentile = round(below / len(sector_cagrs) * 100)
        row.figures.append(Figure("sector_median_cagr", "Sector median", median, "pct"))
        row.figures.append(Figure("sector_percentile", "Within its sector", float(percentile), "count", f"{ordinal(percentile)} percentile"))
    else:
        row.notes.append("Too few sector peers for a median")
    prior, latest = years[-2], years[-1]
    if _has(prior.revenue) and prior.revenue > 0 and _has(latest.revenue):
        latest_growth = (latest.revenue / prior.revenue - 1) * 100
        row.figures.append(Figure("latest_growth", "Latest fiscal year growth", latest_growth, "pct"))
        row.figures.append(Figure("latest_vs_cagr", "Latest year vs own 5-year CAGR", latest_growth - cagr, "pp"))
    base = years[-(GROWTH_YEARS + 1)]
    before_base = years[-(GROWTH_YEARS + 2)] if len(years) >= GROWTH_YEARS + 2 else None
    if (
        before_base is not None
        and _has(before_base.revenue)
        and before_base.revenue > 0
        and _has(base.revenue)
        and base.period_end is not None
        and COVID_FYE_FROM <= base.period_end <= COVID_FYE_TO
        and base.revenue <= before_base.revenue * (1 - COVID_BASE_DROP_PCT / 100)
    ):
        row.notes.append("The base year is a COVID trough, which flatters the 5-year CAGR")
    return row


# --- row 12: ROIC trend ------------------------------------------------------------------------------------------------------


def roic_row(years: list[FiscalYear], company_type: str | None, exempt: dict[str, str]) -> StuckRow:
    row = StuckRow("roic", 12, "Return on invested capital", None)
    if "12" in exempt:
        row.status, row.reason = NOT_APPLICABLE, exempt["12"]
        return row
    if company_type != ROIC_STANDARD_ONLY:
        row.status, row.reason = NOT_APPLICABLE, "Not meaningful for this company type"
        return row
    # Exact zeros are FMP's "no figure" (pre-IPO and spin-off years), dropped as Step 4 does (scoring/step4.py::real_ratio_points).
    points = [y.roic_pct for y in years[-MARGIN_YEARS:] if _has(y.roic_pct) and y.roic_pct != 0.0]
    if len(points) < MIN_LABELLED_YEARS:
        row.status, row.reason = NOT_REPORTED, "Fewer than 3 fiscal years of ROIC"
        return row
    row.figures = [
        Figure("roic_first", "Earliest year", points[0], "pct"),
        Figure("roic_latest", "Latest year", points[-1], "pct"),
        Figure("roic_slope", "Trend per year", _slope(points), "pp"),
    ]
    return row


# --- row 7: price rows (stored values) ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredPriceValues:
    """Read straight from the TickerScore row; nothing here is recomputed."""

    overall_verdict: str | None = None
    valuation_verdict: str | None = None
    weinstein_stage: str | None = None
    weinstein_since: date | None = None
    weinstein_since_is_lower_bound: bool | None = None
    perf_5y_vs_spy_status: str | None = None
    perf_5y_vs_spy_pct: float | None = None


def price_context_row(stored: StoredPriceValues | None) -> StuckRow:
    row = StuckRow("price_context", 7, "Price context", None)
    if stored is None:
        row.status, row.reason = NOT_REPORTED, "No stored score for this ticker yet"
        return row
    row.figures = [
        Figure("overall_verdict", "Overall verdict", None, "text", stored.overall_verdict),
        Figure("valuation_verdict", "Valuation verdict", None, "text", stored.valuation_verdict),
        Figure("weinstein_stage", "Weinstein stage", None, "text", stored.weinstein_stage),
        Figure("perf_5y_vs_spy", "5Y vs SPY", stored.perf_5y_vs_spy_pct, "pp", stored.perf_5y_vs_spy_status),
    ]
    if stored.weinstein_since is not None:
        row.figures.append(
            Figure("weinstein_since", "Stage since", None, "text", stored.weinstein_since.isoformat())
        )
        if stored.weinstein_since_is_lower_bound:
            row.notes.append("The stage-since date is a lower bound (older than the history window)")
    return row


# --- row 8: relative strength ------------------------------------------------------------------------------------------------


def _word(diff_pp: float | None, band_pp: float) -> str | None:
    if diff_pp is None:
        return None
    if abs(diff_pp) <= band_pp:
        return "in line"
    return "leads" if diff_pp > 0 else "trails"


def relative_strength_row(
    stock: dict[int, float | None],
    sector: dict[int, float | None] | None,
    spy: dict[int, float | None],
    sector_etf: str | None,
    band_pp: float,
    sector_weight_pct: float | None = None,
) -> StuckRow:
    """Returns in percent per window in months. `sector` is None when the FMP sector has no SPDR mapping."""
    row = StuckRow("relative_strength", 8, "Relative strength", None)
    if sector is None or sector_etf is None:
        row.status, row.reason = NOT_APPLICABLE, "No sector ETF for this sector"
        return row
    if all(stock.get(m) is None for m in RELATIVE_STRENGTH_WINDOWS):
        row.status, row.reason = NOT_REPORTED, "No cached daily bars for this ticker"
        return row

    def diff(a: dict[int, float | None], b: dict[int, float | None], months: int) -> float | None:
        x, y = a.get(months), b.get(months)
        return x - y if x is not None and y is not None else None

    labels = {1: "1 month", 3: "3 months", 6: "6 months", 12: "12 months"}
    for months in (6, 12, 3, 1):  # headline first, then secondary
        d = diff(stock, sector, months)
        row.figures.append(Figure(f"vs_sector_{months}m", f"vs {sector_etf}, {labels[months]}", d, "pp", _word(d, band_pp)))
    for months in (6, 12):
        d = diff(stock, spy, months)
        row.figures.append(Figure(f"vs_spy_{months}m", f"vs SPY, {labels[months]}", d, "pp", _word(d, band_pp)))
    if sector_weight_pct is not None and sector_weight_pct > WEIGHT_NOTE_PCT_OF_SECTOR:
        row.notes.append(
            f"This stock is {sector_weight_pct:.0f}% of its sector's tracked market cap, so the sector ETF partly measures the stock itself"
        )
    return row


# --- assembly ----------------------------------------------------------------------------------------------------------------

LABELLED_ROW_KEYS = ("cash_conversion", "sbc", "fcf_after_sbc", "share_count")


def footer_line(rows: list[StuckRow]) -> str | None:
    """"Nothing flagged (k of 4 labelled rows assessed)" when none of rows 1, 2, 3, 5 is Flagged; None otherwise. k counts those
    four rows whose status is OK or Flagged (Not applicable, Not reported and an unlabelled row do not count)."""
    labelled = [r for r in rows if r.key in LABELLED_ROW_KEYS]
    if any(r.status == FLAGGED for r in labelled):
        return None
    assessed = sum(1 for r in labelled if r.status == OK)
    return f"Nothing flagged ({assessed} of 4 labelled rows assessed)"


def evaluate_fundamental_rows(
    years: list[FiscalYear],
    company_type: str | None,
    ticker: str,
    ipo_date: date | None,
    settings: StuckSettings,
    sector_cagrs: list[float],
) -> list[StuckRow]:
    """Rows 1-6, 9, 10 and 12 (chronological `years`, completed fiscal years). Rows 7 and 8 come from `price_context_row` and
    `relative_strength_row`; the data module orders all of them."""
    exempt = exempt_rows(ticker, company_type, settings)
    window = post_listing_years(years, ipo_date)
    sbc, after, buybacks = sbc_rows(window, settings, exempt)
    rows = [
        cash_conversion_row(years, settings, exempt),
        sbc,
        after,
        *([buybacks] if buybacks is not None else []),
        share_count_row(window, company_type, settings, exempt),
        shareholder_yield_row(years, exempt),
        margins_row(years, company_type, exempt),
        growth_row(years, sector_cagrs, exempt),
        roic_row(years, company_type, exempt),
    ]
    return rows


__all__ = [
    "DEFAULT_STUCK_SETTINGS",
    "EXEMPTABLE_ROWS",
    "Exemption",
    "FLAGGED",
    "Figure",
    "FiscalYear",
    "NOT_APPLICABLE",
    "NOT_REPORTED",
    "OK",
    "StoredPriceValues",
    "StuckResult",
    "StuckRow",
    "StuckSettings",
    "evaluate_fundamental_rows",
    "footer_line",
]
