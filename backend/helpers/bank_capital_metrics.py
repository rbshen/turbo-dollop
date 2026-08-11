from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from core.models import TickerBankCapitalMetrics
from core.tickers import normalize_ticker


def get_ticker_bank_capital_metrics(session: Session, ticker: str) -> TickerBankCapitalMetrics | None:
    """None means "not set" -- same non-get-or-create convention as
    moat.py::get_ticker_moat: "not set" (CET1 not yet entered, no NPL
    override) is itself a meaningful, valid state for a Bank ticker, not a
    placeholder waiting to be filled in."""
    return session.get(TickerBankCapitalMetrics, normalize_ticker(ticker))


def set_ticker_bank_capital_metrics(
    session: Session,
    ticker: str,
    cet1_ratio_pct: float | None,
    cet1_as_of: str | None,
    npl_ratio_pct: float | None,
    npl_as_of: str | None,
) -> TickerBankCapitalMetrics:
    """Full-replace upsert, same sqlite on_conflict_do_update pattern as
    moat.py::set_ticker_moat -- every field is overwritten with whatever the
    caller passes, including None, so a PUT can also clear a previously-set
    CET1 value or NPL override, not just set one."""
    ticker = normalize_ticker(ticker)
    now = datetime.now()
    values = {
        "ticker": ticker,
        "cet1_ratio_pct": cet1_ratio_pct,
        "cet1_as_of": cet1_as_of,
        "npl_ratio_pct": npl_ratio_pct,
        "npl_as_of": npl_as_of,
        "updated_at": now,
    }
    stmt = sqlite_insert(TickerBankCapitalMetrics).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker"],
        set_={
            "cet1_ratio_pct": cet1_ratio_pct,
            "cet1_as_of": cet1_as_of,
            "npl_ratio_pct": npl_ratio_pct,
            "npl_as_of": npl_as_of,
            "updated_at": now,
        },
    )
    session.execute(stmt)
    session.commit()
    return session.get(TickerBankCapitalMetrics, ticker)
