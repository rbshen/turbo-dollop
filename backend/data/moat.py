from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from core.models import MoatScoreConfig, TickerMoat
from core.tickers import normalize_ticker
from scoring.overall import DEFAULT_NARROW_MOAT_MULTIPLIER, NARROW_MOAT_MULTIPLIER_OPTIONS, moat_multiplier

# The Narrow multiplier a fresh database starts with; from then on the DB row (editable via /settings > Economic Moat) is the
# source of truth. Wide (1.0) and No moat / not rated (0.70) are constants in scoring/overall.py, never stored.
CONFIG_KEY = "default"

VALID_MOAT_VALUES = {"no_moat", "narrow_moat", "wide_moat"}


def get_ticker_moat(session: Session, ticker: str) -> TickerMoat | None:
    """None means "not set" -- the default for every ticker until a user
    explicitly sets one via the Economic Moat tab. No get-or-create here,
    unlike get_moat_score_config: unlike the config's point values (which
    always need a concrete number to compute with), "not set" is itself a
    meaningful, valid state, not a placeholder waiting to be filled in."""
    return session.get(TickerMoat, normalize_ticker(ticker))


def set_ticker_moat(session: Session, ticker: str, moat: str) -> TickerMoat:
    ticker = normalize_ticker(ticker)
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
    rather than via a separate seed script). The row holds the Narrow multiplier; readers treat a NULL one (a row that predates the column and
    was not migrated) as the default (resolve_moat_multiplier)."""
    row = session.get(MoatScoreConfig, CONFIG_KEY)
    if row is not None:
        return row

    row = MoatScoreConfig(
        key=CONFIG_KEY, narrow_moat_multiplier=DEFAULT_NARROW_MOAT_MULTIPLIER, updated_at=datetime.now()
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_moat_score_config(session: Session, narrow_moat_multiplier: float) -> MoatScoreConfig:
    """Saves the Narrow multiplier. The caller has validated it against NARROW_MOAT_MULTIPLIER_OPTIONS (MoatScoreConfigIn does);
    this refuses anything else too, so no other path can store an unsupported value."""
    if narrow_moat_multiplier not in NARROW_MOAT_MULTIPLIER_OPTIONS:
        raise ValueError(f"Narrow moat multiplier must be one of {', '.join(f'{v:.2f}' for v in NARROW_MOAT_MULTIPLIER_OPTIONS)}.")
    row = get_moat_score_config(session)
    row.narrow_moat_multiplier = narrow_moat_multiplier
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def resolve_moat_multiplier(config: MoatScoreConfig | None, moat: str | None) -> float:
    """The multiplier for a Moat state (None = unset = No moat) under the saved Narrow setting (the default when no config)."""
    narrow = (config.narrow_moat_multiplier if config is not None else None) or DEFAULT_NARROW_MOAT_MULTIPLIER
    return moat_multiplier(moat, narrow)
