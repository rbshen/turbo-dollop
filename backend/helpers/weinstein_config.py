from dataclasses import asdict
from datetime import datetime

from sqlmodel import Session

from analysis.trend_structure.weinstein import WeinsteinParams
from core.models import WeinsteinSettings

_CONFIG_KEY = "default"

_FIELDS = tuple(asdict(WeinsteinParams()).keys())


def get_weinstein_settings(session: Session) -> WeinsteinSettings:
    """Get-or-create (no migration tooling in this app -- see
    LiquidityZoneSettings): a first-boot default row is seeded lazily on
    first read."""
    row = session.get(WeinsteinSettings, _CONFIG_KEY)
    if row is None:
        row = WeinsteinSettings(key=_CONFIG_KEY, updated_at=datetime.now(), **asdict(WeinsteinParams()))
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def update_weinstein_settings(session: Session, **values) -> WeinsteinSettings:
    row = get_weinstein_settings(session)
    for field in _FIELDS:
        setattr(row, field, values[field])
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def to_engine_params(row: WeinsteinSettings) -> WeinsteinParams:
    """Row -> the pure engine's frozen dataclass (the engine never sees a
    SQLModel table)."""
    return WeinsteinParams(**{f: getattr(row, f) for f in _FIELDS})


def load_weinstein_params(session: Session) -> WeinsteinParams:
    """Live read of the current settings -- call at compute time, never cache."""
    return to_engine_params(get_weinstein_settings(session))
