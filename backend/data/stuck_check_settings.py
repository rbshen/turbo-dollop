"""Where the "Why might it be stuck?" thresholds live: one singleton row, a short in-process cache, and the save/reset writes
(scoring/stuck_check.py is the pure definition: shape, defaults, bounds). Same shape as data/score_weights.py.

Reads NEVER write: an unseeded database (or one without the table) serves DEFAULT_STUCK_SETTINGS. The row is created by the first
save, reset or GET of the settings endpoint. Nothing here recomputes anything: the card reads the settings on every load.
"""

import json
import time
from datetime import datetime

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from core.models import StuckCheckSettings
from scoring.stuck_check import DEFAULT_STUCK_SETTINGS, Exemption, StuckSettings

CONFIG_KEY = "default"
CACHE_TTL_SECONDS = 5.0

NUMERIC_FIELDS = (
    "sbc_revenue_pct",
    "sbc_fcf_pct",
    "cash_conversion_line",
    "share_growth_pct",
    "one_off_pct",
    "sector_band_pp",
    "smoothing_days",
)


def exemptions_to_json(exemptions: tuple[Exemption, ...]) -> str:
    return json.dumps([{"ticker": e.ticker, "reason": e.reason, "rows": list(e.rows)} for e in exemptions])


def exemptions_from_json(raw: str) -> tuple[Exemption, ...]:
    try:
        data = json.loads(raw)
        return tuple(Exemption(str(e["ticker"]), str(e["reason"]), tuple(str(r) for r in e["rows"])) for e in data)
    except (ValueError, KeyError, TypeError):
        return DEFAULT_STUCK_SETTINGS.exemptions


def settings_of(row: StuckCheckSettings) -> StuckSettings:
    values = {name: getattr(row, name) for name in NUMERIC_FIELDS}
    values["smoothing_days"] = int(values["smoothing_days"])
    return StuckSettings(**values, exemptions=exemptions_from_json(row.exemptions_json))


_cache: tuple[int, float, StuckSettings] | None = None  # (id(engine), loaded_at, settings)


def invalidate_cache() -> None:
    global _cache
    _cache = None


def load_stuck_settings(bind: Engine) -> StuckSettings:
    """The saved thresholds (or the code defaults when nothing was ever saved), from the cache when under 5 s old. Read-only."""
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] == id(bind) and now - _cache[1] < CACHE_TTL_SECONDS:
        return _cache[2]
    try:
        with Session(bind) as session:
            row = session.get(StuckCheckSettings, CONFIG_KEY)
    except OperationalError:  # no such table yet (an engine that never ran init_db): the defaults, exactly as for no row
        row = None
    loaded = settings_of(row) if row is not None else DEFAULT_STUCK_SETTINGS
    _cache = (id(bind), now, loaded)
    return loaded


def _values(settings: StuckSettings) -> dict:
    return {**{name: getattr(settings, name) for name in NUMERIC_FIELDS}, "exemptions_json": exemptions_to_json(settings.exemptions)}


def get_stuck_settings_row(session: Session) -> StuckCheckSettings:
    """Get-or-create (this app seeds lazily, see data/score_weights.py): the singleton row."""
    row = session.get(StuckCheckSettings, CONFIG_KEY)
    if row is None:
        row = StuckCheckSettings(key=CONFIG_KEY, updated_at=datetime.now(), **_values(DEFAULT_STUCK_SETTINGS))
        session.add(row)
        session.commit()
        session.refresh(row)
        invalidate_cache()
    return row


def save_stuck_settings(session: Session, settings: StuckSettings) -> StuckCheckSettings:
    """Writes the set (already validated by the caller)."""
    row = get_stuck_settings_row(session)
    for name, value in _values(settings).items():
        setattr(row, name, value)
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    invalidate_cache()
    return row


def reset_stuck_settings(session: Session) -> StuckCheckSettings:
    """Restores the code defaults, the seeded exemption list included."""
    return save_stuck_settings(session, DEFAULT_STUCK_SETTINGS)
