from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from models import MoatScoreConfig, TickerMoat

# Seeded only as the config row's initial value on first read (see
# get_moat_score_config) -- from then on the DB row (editable via
# /settings) is the source of truth, not these constants.
DEFAULT_WIDE_MOAT_SCORE = 100.0
DEFAULT_NARROW_MOAT_SCORE = 65.0
DEFAULT_NO_MOAT_SCORE = 0.0

CONFIG_KEY = "default"

VALID_MOAT_VALUES = {"no_moat", "narrow_moat", "wide_moat"}


def get_ticker_moat(session: Session, ticker: str) -> TickerMoat | None:
    """None means "not set" -- the default for every ticker until a user
    explicitly sets one via the Economic Moat tab. No get-or-create here,
    unlike get_moat_score_config: unlike the config's point values (which
    always need a concrete number to compute with), "not set" is itself a
    meaningful, valid state, not a placeholder waiting to be filled in."""
    return session.get(TickerMoat, ticker.upper())


def set_ticker_moat(session: Session, ticker: str, moat: str) -> TickerMoat:
    ticker = ticker.upper()
    now = datetime.now()
    values = {"ticker": ticker, "moat": moat, "updated_at": now}
    stmt = sqlite_insert(TickerMoat).values(**values)
    stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_={"moat": moat, "updated_at": now})
    session.execute(stmt)
    session.commit()
    return session.get(TickerMoat, ticker)


def get_moat_score_config(session: Session) -> MoatScoreConfig:
    """Get-or-create -- same lazy-seed pattern as
    discount_rate_config.get_discount_rate_config (this app has no
    migration tooling, so a first-boot default row is seeded on first read
    rather than via a separate seed script)."""
    row = session.get(MoatScoreConfig, CONFIG_KEY)
    if row is not None:
        return row

    row = MoatScoreConfig(
        key=CONFIG_KEY,
        wide_moat_score=DEFAULT_WIDE_MOAT_SCORE,
        narrow_moat_score=DEFAULT_NARROW_MOAT_SCORE,
        no_moat_score=DEFAULT_NO_MOAT_SCORE,
        updated_at=datetime.now(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_moat_score_config(
    session: Session, wide_moat_score: float, narrow_moat_score: float, no_moat_score: float
) -> MoatScoreConfig:
    row = get_moat_score_config(session)
    row.wide_moat_score = wide_moat_score
    row.narrow_moat_score = narrow_moat_score
    row.no_moat_score = no_moat_score
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def resolve_moat_score(config: MoatScoreConfig, moat: str) -> float:
    return {
        "wide_moat": config.wide_moat_score,
        "narrow_moat": config.narrow_moat_score,
        "no_moat": config.no_moat_score,
    }[moat]
