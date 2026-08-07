import logging
from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from core.models import TickerCustomValuation
from core.schemas import Step3ManualParams
from scoring.step3 import ManualCalculationResult, run_manual_calculation

logger = logging.getLogger(__name__)


def get_ticker_custom_valuation(session: Session, ticker: str) -> TickerCustomValuation | None:
    """None means "no custom valuation saved" -- the default for every
    ticker until a user explicitly saves one via the Custom Valuation
    panel. No get-or-create, same convention as moat.py::get_ticker_moat."""
    return session.get(TickerCustomValuation, ticker.upper())


def set_ticker_custom_valuation(session: Session, ticker: str, method: str, parameters_json: str) -> TickerCustomValuation:
    """Upserts method/parameters_json/saved_at only -- deliberately never
    touches is_active. Saving a brand-new valuation leaves it inactive
    (Auto Calculation stays live) until activate_ticker_custom_valuation is
    called separately; saving over an already-active valuation leaves it
    active, so the new values take effect immediately (there's no
    draft/live split -- one row per ticker is the live row whenever
    is_active is True)."""
    ticker = ticker.upper()
    now = datetime.now()
    values = {"ticker": ticker, "method": method, "parameters_json": parameters_json, "is_active": False, "saved_at": now}
    stmt = sqlite_insert(TickerCustomValuation).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker"], set_={"method": method, "parameters_json": parameters_json, "saved_at": now}
    )
    session.execute(stmt)
    session.commit()
    return session.get(TickerCustomValuation, ticker)


def activate_ticker_custom_valuation(session: Session, ticker: str) -> TickerCustomValuation | None:
    """None if no row has ever been saved for this ticker -- the caller
    (the /activate endpoint) turns that into a 404 rather than silently
    creating an empty row to activate."""
    row = get_ticker_custom_valuation(session, ticker)
    if row is None:
        return None
    row.is_active = True
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def deactivate_ticker_custom_valuation(session: Session, ticker: str) -> TickerCustomValuation | None:
    """None if no row exists -- a no-op, not an error (mirrors activate's
    own None convention for "nothing to act on")."""
    row = get_ticker_custom_valuation(session, ticker)
    if row is None:
        return None
    row.is_active = False
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def parse_custom_valuation_params(parameters_json: str) -> Step3ManualParams | None:
    """None if parameters_json is corrupt -- e.g. a future field rename
    ever hit an old saved row without a data migration. Callers (the
    step3_data.py choke point, the custom-valuation endpoints) must treat
    this the same as "no usable custom valuation", never crash the whole
    ticker page/summary/score request over it."""
    try:
        return Step3ManualParams.model_validate_json(parameters_json)
    except ValueError:
        logger.warning("Failed to parse a saved TickerCustomValuation.parameters_json value -- treating as corrupt")
        return None


def run_manual_calculation_from_params(method: str, params: Step3ManualParams, last_close: float | None) -> ManualCalculationResult:
    """Thin adapter from the Step3ManualParams shape (what's saved/loaded
    for a persistent custom valuation) to scoring.step3.run_manual_
    calculation's own by-name parameter list -- shared by
    step3_data.py::get_active_valuation and the custom-valuation save/GET
    endpoints (main.py), so the 13-field call site exists exactly once."""
    return run_manual_calculation(
        method=method,
        current_value=params.current_value,
        growth_yr_1_5=params.growth_yr_1_5,
        growth_yr_6_10=params.growth_yr_6_10,
        growth_yr_11_20=params.growth_yr_11_20,
        discount_rate=params.discount_rate,
        shares_outstanding=params.shares_outstanding,
        total_debt=params.total_debt,
        cash_and_st_investments=params.cash_and_st_investments,
        book_value_per_share=params.book_value_per_share,
        pb_mean_ratio=params.pb_mean_ratio,
        pb_sd_ratio=params.pb_sd_ratio,
        sales_per_share=params.sales_per_share,
        projected_growth_rate=params.projected_growth_rate,
        fair_psg_ratio=params.fair_psg_ratio,
        last_close=last_close,
    )


def delete_ticker_custom_valuation(session: Session, ticker: str) -> bool:
    """Deletes the row outright regardless of is_active -- reverting an
    active valuation to Auto Calculation is a side effect of there being no
    row left for get_active_valuation to find, not a separate step. Returns
    whether a row existed to delete, so the caller can decide whether a
    Screener/Watchlist recompute is actually needed."""
    row = get_ticker_custom_valuation(session, ticker)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
