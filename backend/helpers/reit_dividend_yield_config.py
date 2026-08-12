from datetime import datetime

from sqlmodel import Session

from core.models import ReitDividendYieldConfig

# Framework default (valuation.md §3.3) -- seeded here only as the row's
# initial value on first read. From then on the DB row (editable via
# /settings) is the source of truth, not this constant.
REIT_DIVIDEND_YIELD_THRESHOLD_DEFAULT_PCT = 5.0

CONFIG_KEY = "default"


def get_reit_dividend_yield_config(session: Session) -> ReitDividendYieldConfig:
    """Get-or-create -- this app has no migration tooling (db.init_db() is
    a plain SQLModel.metadata.create_all), so a first-boot default row is
    seeded lazily on first read rather than via a separate seed script."""
    row = session.get(ReitDividendYieldConfig, CONFIG_KEY)
    if row is not None:
        return row

    row = ReitDividendYieldConfig(
        key=CONFIG_KEY,
        threshold_pct=REIT_DIVIDEND_YIELD_THRESHOLD_DEFAULT_PCT,
        updated_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_reit_dividend_yield_config(session: Session, threshold_pct: float) -> ReitDividendYieldConfig:
    row = get_reit_dividend_yield_config(session)
    row.threshold_pct = threshold_pct
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
