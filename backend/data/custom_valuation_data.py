from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from core.models import TickerCustomValuation


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
